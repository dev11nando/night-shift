"""Pipeline noturno, etapas 1 a 5 do escopo:
collect → hard_filter → embed_rank → llm_score → documents (CV ajustado + carta).

Cada etapa é idempotente (só processa o que ainda não foi processado), confere o pedido
de parada entre unidades de trabalho e grava contagens no ``Run``.
"""

import re
import time
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from pathlib import Path

from sqlalchemy.orm import Session, sessionmaker

from night_shift.adapters.storage.documents import DocumentsRepository
from night_shift.adapters.storage.models import Job, Run, Score, utcnow
from night_shift.adapters.storage.repository import JobRepository, to_posting
from night_shift.application.documents import (
    LETTER_SYSTEM,
    TAILOR_SYSTEM,
    CoverLetter,
    job_language,
    letter_prompt,
    tailor_prompt,
    validate_letter,
)
from night_shift.application.scoring import (
    SYSTEM_PROMPT,
    JobFit,
    build_prompt,
    cosine,
    job_text,
)
from night_shift.config import CompanyConfig, CVMaster, Profile
from night_shift.domain.cv import CVSelection, TailoredCV, apply_selection, default_cv
from night_shift.domain.enrich import enrich
from night_shift.domain.enums import RunStatus
from night_shift.domain.filters import HardFilter
from night_shift.domain.job import JobPosting
from night_shift.domain.text import fold
from night_shift.ports import Embedder, JobSource, LLMProvider, LLMUnavailable, SourceError
from night_shift.runtime.stop_flag import StopFlag

EMBED_BATCH = 16


def slugify(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", fold(text)).strip("-")[:40] or "vaga"


class Stopped(Exception):
    """Pedido de parada (``run/STOP``) atendido entre etapas."""


@dataclass
class Pipeline:
    sessions: sessionmaker[Session]
    stop: StopFlag
    log: Callable[[str], None] = print
    clock: Callable[[], float] = time.monotonic
    stats: dict[str, int] = field(default_factory=dict)
    errors: list[str] = field(default_factory=list)
    # Prazo compartilhado pelas etapas que usam LLM numa mesma execução.
    deadline: float | None = None

    def _check_stop(self) -> None:
        if self.stop.is_set():
            raise Stopped

    def _count(self, key: str, n: int = 1) -> None:
        self.stats[key] = self.stats.get(key, 0) + n

    def _error(self, msg: str) -> None:
        self.errors.append(msg)
        self.log(f"  erro: {msg}")

    def start_budget(self, seconds: float | None) -> None:
        """Começa a contar o tempo das etapas de LLM (só na primeira chamada da execução)."""
        if seconds and self.deadline is None:
            self.deadline = self.clock() + seconds

    def _time_up(self, remaining: int, key: str) -> bool:
        if self.deadline is not None and self.clock() >= self.deadline:
            self._count(key, remaining)
            self.log(f"  tempo esgotado: {remaining} vaga(s) ficam para a próxima execução")
            return True
        return False

    # ------------------------------------------------------------------ etapas

    def collect(self, sources: Sequence[JobSource], companies: Sequence[CompanyConfig]) -> None:
        self.log("coleta")
        with self.sessions.begin() as s:
            company_ids = JobRepository(s).sync_companies(companies)
        for source in sources:
            self._check_stop()
            try:
                postings = [enrich(p) for p in source.fetch()]
            except SourceError as e:
                self._error(f"{source.name}: {e}")
                continue
            with self.sessions.begin() as s:
                repo = JobRepository(s)
                new = sum(repo.add_if_new(p, company_ids.get(p.company_name)) for p in postings)
            self._count("collected", len(postings))
            self._count("new", new)
            self.log(f"  {source.name}: {len(postings)} vagas, {new} novas")

    def screen(self, hard_filter: HardFilter) -> None:
        self.log("filtro por regra")
        with self.sessions.begin() as s:
            repo = JobRepository(s)
            for job in repo.unscreened():
                result = hard_filter.evaluate(to_posting(job))
                repo.save_screening(job, result.reason)
                self._count("passed_filter" if result.passed else "filtered_out")
        self.log(
            f"  {self.stats.get('passed_filter', 0)} passaram, "
            f"{self.stats.get('filtered_out', 0)} cortadas"
        )

    def embed_rank(self, embedder: Embedder, cv_text: str) -> None:
        self.log(f"similaridade ({embedder.model})")
        with self.sessions() as s:
            pending_ids = [sc.id for sc in JobRepository(s).needing_similarity()]
        if not pending_ids:
            return
        [cv_vec] = embedder.embed([cv_text])
        for i in range(0, len(pending_ids), EMBED_BATCH):
            self._check_stop()
            with self.sessions.begin() as s:
                batch = [s.get_one(Score, sid) for sid in pending_ids[i : i + EMBED_BATCH]]
                vectors = embedder.embed([job_text(to_posting(sc.job)) for sc in batch])
                for sc, vec in zip(batch, vectors, strict=True):
                    sc.embed_similarity = cosine(cv_vec, vec)
            self._count("embedded", len(batch))
        self.log(f"  {len(pending_ids)} vagas comparadas com o CV")

    def llm_score(
        self,
        llm: LLMProvider,
        profile: Profile,
        cv_text: str,
        top_n: int,
        budget_seconds: float | None = None,
    ) -> None:
        """Dá nota às top N. Com ``budget_seconds``, para de pegar vaga nova quando o tempo
        acaba; as restantes ficam para a próxima execução."""
        budget = f", limite {budget_seconds / 60:.0f} min" if budget_seconds else ""
        self.log(f"nota do LLM ({llm.model}, top {top_n}{budget})")
        self.start_budget(budget_seconds)
        with self.sessions() as s:
            ids = [sc.id for sc in JobRepository(s).top_unscored(top_n)]
        for n, sid in enumerate(ids, 1):
            self._check_stop()
            if self._time_up(len(ids) - n + 1, "llm_deferred"):
                break
            with self.sessions.begin() as s:
                sc = s.get_one(Score, sid)
                job = to_posting(sc.job)
                try:
                    fit = llm.complete_json(
                        SYSTEM_PROMPT, build_prompt(profile, cv_text, job), JobFit
                    )
                except LLMUnavailable:
                    raise
                except Exception as e:  # uma vaga problemática não derruba as outras
                    self._error(f"LLM em '{job.title}': {e}")
                    continue
                JobRepository(s).save_llm_score(
                    sc, fit.score, fit.rationale, fit.red_flags, llm.model
                )
            self._count("llm_scored")
            self.log(f"  [{n}/{len(ids)}] {fit.score:3d}  {job.title} — {job.company_name}")

    def documents(
        self,
        llm: LLMProvider,
        profile: Profile,
        cv: CVMaster,
        render: Callable[[TailoredCV, Path], Path],
        out_dir: Path,
        min_score: int,
        limit: int,
        budget_seconds: float | None = None,
    ) -> None:
        """CV ajustado (PDF) e carta para as melhores vagas da fila que ainda não têm.

        Seleção do CV rejeitada pelo validador: tenta de novo uma vez com o motivo, depois
        usa o CV mestre sem ajuste. Carta rejeitada: tenta de novo uma vez, depois fica sem.
        """
        self.log(f"CV ajustado + carta ({llm.model}, nota >= {min_score}, até {limit})")
        self.start_budget(budget_seconds)
        with self.sessions() as s:
            ids = [sc.job_id for sc in DocumentsRepository(s).needing_documents(min_score, limit)]
        for n, job_id in enumerate(ids, 1):
            self._check_stop()
            if self._time_up(len(ids) - n + 1, "documents_deferred"):
                break
            with self.sessions() as s:
                job = to_posting(s.get_one(Job, job_id))

            tailored = self._tailor(llm, cv, job)
            pdf = render(tailored, out_dir / f"{job_id}-{slugify(job.company_name)}.pdf")
            letter = self._letter(llm, profile, cv, job)

            with self.sessions.begin() as s:
                DocumentsRepository(s).save_documents(job_id, pdf, letter)
            self._count("documents")
            suffix = "" if letter else "  (sem carta)"
            self.log(f"  [{n}/{len(ids)}] {job.title} — {job.company_name}{suffix}")

    def _two_tries[T](self, what: str, job: JobPosting, attempt: Callable[[str], T]) -> T | None:
        """Chama ``attempt(feedback)`` até 2 vezes; na 2ª, o feedback é o erro da 1ª."""
        feedback, last = "", None
        for _ in range(2):
            try:
                return attempt(feedback)
            except LLMUnavailable:
                raise
            except Exception as e:
                last = e
                feedback = f"\n\nA tentativa anterior foi rejeitada: {e}. Corrija isso."
        self._error(f"{what} em '{job.title}': {last}")
        return None

    def _tailor(self, llm: LLMProvider, cv: CVMaster, job: JobPosting) -> TailoredCV:
        def attempt(feedback: str) -> TailoredCV:
            sel = llm.complete_json(TAILOR_SYSTEM, tailor_prompt(cv, job) + feedback, CVSelection)
            return apply_selection(cv, sel)

        return self._two_tries("seleção do CV", job, attempt) or default_cv(cv)

    def _letter(
        self, llm: LLMProvider, profile: Profile, cv: CVMaster, job: JobPosting
    ) -> CoverLetter | None:
        prompt = letter_prompt(profile, cv, job, job_language(job))

        def attempt(feedback: str) -> CoverLetter:
            letter = llm.complete_json(LETTER_SYSTEM, prompt + feedback, CoverLetter)
            return validate_letter(letter, profile, cv, job)

        return self._two_tries("carta", job, attempt)

    # ------------------------------------------------------------- orquestração

    def run(self, steps: Sequence[Callable[[], None]]) -> Run:
        """Executa as etapas registrando um ``Run``. Nunca propaga ``Stopped``."""
        self.stats.clear()
        self.errors.clear()
        self.deadline = None
        with self.sessions.begin() as s:
            run_id = JobRepository(s).start_run().id
        status = RunStatus.SUCCESS
        try:
            for step in steps:
                step()
        except Stopped:
            status = RunStatus.STOPPED
            self.log("parada solicitada: encerrando entre etapas")
        except LLMUnavailable as e:
            status = RunStatus.FAILED
            self._error(str(e))
        except Exception as e:
            status = RunStatus.FAILED
            self._error(f"{type(e).__name__}: {e}")
            raise
        finally:
            with self.sessions.begin() as s:
                run = s.get_one(Run, run_id)
                run.status, run.finished_at = status, utcnow()
                run.stats, run.errors = dict(self.stats), list(self.errors)
        with self.sessions() as s:
            return s.get_one(Run, run_id)
