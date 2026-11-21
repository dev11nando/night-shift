"""Pipeline noturno, etapas 1 a 4 do escopo: collect → hard_filter → embed_rank → llm_score.

Cada etapa é idempotente (só processa o que ainda não foi processado), confere o pedido
de parada entre unidades de trabalho e grava contagens no ``Run``.
"""

from collections.abc import Callable, Sequence
from dataclasses import dataclass, field

from sqlalchemy.orm import Session, sessionmaker

from night_shift.adapters.storage.models import Run, Score, utcnow
from night_shift.adapters.storage.repository import JobRepository, to_posting
from night_shift.application.scoring import (
    SYSTEM_PROMPT,
    JobFit,
    build_prompt,
    cosine,
    job_text,
)
from night_shift.config import CompanyConfig, Profile
from night_shift.domain.enums import RunStatus
from night_shift.domain.filters import HardFilter
from night_shift.ports import Embedder, JobSource, LLMProvider, LLMUnavailable, SourceError
from night_shift.runtime.stop_flag import StopFlag

EMBED_BATCH = 16


class Stopped(Exception):
    """Pedido de parada (``run/STOP``) atendido entre etapas."""


@dataclass
class Pipeline:
    sessions: sessionmaker[Session]
    stop: StopFlag
    log: Callable[[str], None] = print
    stats: dict[str, int] = field(default_factory=dict)
    errors: list[str] = field(default_factory=list)

    def _check_stop(self) -> None:
        if self.stop.is_set():
            raise Stopped

    def _count(self, key: str, n: int = 1) -> None:
        self.stats[key] = self.stats.get(key, 0) + n

    def _error(self, msg: str) -> None:
        self.errors.append(msg)
        self.log(f"  erro: {msg}")

    # ------------------------------------------------------------------ etapas

    def collect(self, sources: Sequence[JobSource], companies: Sequence[CompanyConfig]) -> None:
        self.log("coleta")
        with self.sessions.begin() as s:
            company_ids = JobRepository(s).sync_companies(companies)
        for source in sources:
            self._check_stop()
            try:
                postings = list(source.fetch())
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

    def llm_score(self, llm: LLMProvider, profile: Profile, cv_text: str, top_n: int) -> None:
        self.log(f"nota do LLM ({llm.model}, top {top_n})")
        with self.sessions() as s:
            ids = [sc.id for sc in JobRepository(s).top_unscored(top_n)]
        for n, sid in enumerate(ids, 1):
            self._check_stop()
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

    # ------------------------------------------------------------- orquestração

    def run(self, steps: Sequence[Callable[[], None]]) -> Run:
        """Executa as etapas registrando um ``Run``. Nunca propaga ``Stopped``."""
        self.stats.clear()
        self.errors.clear()
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
