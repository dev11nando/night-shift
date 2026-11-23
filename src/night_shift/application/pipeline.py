"""Pipeline noturno, etapas 1 a 5 do escopo:
collect → hard_filter → embed_rank → llm_score → documents (CV ajustado + carta).

Cada etapa é idempotente (só processa o que ainda não foi processado), confere o pedido
de parada entre unidades de trabalho e grava contagens no ``Run``.
"""

import re
import time
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from pathlib import Path

from sqlalchemy.orm import Session, sessionmaker

from night_shift.adapters.storage.documents import DocumentsRepository
from night_shift.adapters.storage.models import Company, Job, Run, Score, utcnow
from night_shift.adapters.storage.outreach import OutreachRepository
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
from night_shift.application.outreach import SYSTEM as OUTREACH_SYSTEM
from night_shift.application.outreach import (
    OutreachMessage,
    outreach_prompt,
    validate_outreach,
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
from night_shift.domain.naming import clear_cv_variants, cv_filename
from night_shift.domain.stacks import DEFAULT_STACK
from night_shift.domain.text import fold
from night_shift.ports import Embedder, JobSource, LLMProvider, LLMUnavailable, SourceError
from night_shift.runtime.stop_flag import StopFlag

EMBED_BATCH = 16


def per_stack[T](value: T | dict[str, T]) -> dict[str, T]:
    """Um valor só vira o perfil padrão; um dict já é ``{stack: valor}``."""
    return value if isinstance(value, dict) else {DEFAULT_STACK: value}


def pick[T](values: dict[str, T], stack: str | None) -> T:
    """Valor do perfil da stack, ou o do perfil padrão (ou o primeiro que houver)."""
    if stack in values:
        return values[stack]
    return values.get(DEFAULT_STACK) or next(iter(values.values()))


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
    # Progresso ao vivo: gravado na linha do Run a cada unidade de trabalho.
    run_id: int | None = None
    log_path: str | None = None
    budget_ends_at: datetime | None = None

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
            self.budget_ends_at = utcnow() + timedelta(seconds=seconds)

    def _progress(self, stage: str | None = None, item: str | None = None) -> None:
        """Atualiza a linha do Run para a página /ao-vivo. Sem Run (testes), não faz nada."""
        if self.run_id is None:
            return
        with self.sessions.begin() as s:
            run = s.get(Run, self.run_id)
            if run is None:
                return
            if stage is not None:
                run.stage = stage
            run.current_item = item[:300] if item else None
            run.stats, run.errors = dict(self.stats), list(self.errors)
            run.budget_ends_at = self.budget_ends_at

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
            self._progress("coleta", source.name)
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
        self._progress("filtro")
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

    def embed_rank(
        self,
        embedder: Embedder | Callable[[str], Embedder],
        cv_text: str | dict[str, str],
    ) -> None:
        """Compara cada vaga com o CV do perfil da stack dela. ``embedder`` pode ser um só
        para todos ou uma fábrica que recebe o texto do CV (ex.: palavras-chave do perfil)."""
        texts = per_stack(cv_text)
        self.log("similaridade")
        self._progress("similaridade")
        with self.sessions() as s:
            pending = [(sc.id, sc.job.stack) for sc in JobRepository(s).needing_similarity()]
        if not pending:
            return
        groups: dict[str, list[int]] = {}
        for sid, stack in pending:
            groups.setdefault(stack if stack in texts else DEFAULT_STACK, []).append(sid)
        for stack, ids in groups.items():
            text = texts.get(stack) or texts[DEFAULT_STACK]
            # Classe ou função = fábrica (um embedder por perfil); objeto pronto = um para todos.
            is_factory = isinstance(embedder, type) or not hasattr(embedder, "embed")
            emb = embedder(text) if is_factory else embedder
            [cv_vec] = emb.embed([text])
            for i in range(0, len(ids), EMBED_BATCH):
                self._check_stop()
                with self.sessions.begin() as s:
                    batch = [s.get_one(Score, sid) for sid in ids[i : i + EMBED_BATCH]]
                    vectors = emb.embed([job_text(to_posting(sc.job)) for sc in batch])
                    for sc, vec in zip(batch, vectors, strict=True):
                        sc.embed_similarity = cosine(cv_vec, vec)
                self._count("embedded", len(batch))
        detail = ", ".join(f"{len(ids)} {stack}" for stack, ids in groups.items())
        self.log(f"  {len(pending)} vagas comparadas com o CV ({detail})")

    def llm_score(
        self,
        llm: LLMProvider,
        profile: Profile,
        cv_text: str | dict[str, str],
        top_n: int,
        budget_seconds: float | None = None,
    ) -> None:
        """Dá nota às top N. Com ``budget_seconds``, para de pegar vaga nova quando o tempo
        acaba; as restantes ficam para a próxima execução."""
        budget = f", limite {budget_seconds / 60:.0f} min" if budget_seconds else ""
        self.log(f"nota do LLM ({llm.model}, top {top_n}{budget})")
        self.start_budget(budget_seconds)
        self._progress("nota")
        with self.sessions() as s:
            ids = [sc.id for sc in JobRepository(s).top_unscored(top_n)]
        for n, sid in enumerate(ids, 1):
            self._check_stop()
            if self._time_up(len(ids) - n + 1, "llm_deferred"):
                break
            with self.sessions() as s:
                peek = to_posting(s.get_one(Score, sid).job)
            self._progress("nota", f"[{n}/{len(ids)}] {peek.title} — {peek.company_name}")
            with self.sessions.begin() as s:
                sc = s.get_one(Score, sid)
                job = to_posting(sc.job)
                try:
                    fit = llm.complete_json(
                        SYSTEM_PROMPT,
                        build_prompt(profile, pick(per_stack(cv_text), job.stack), job),
                        JobFit,
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
        cv: CVMaster | dict[str, CVMaster],
        render: Callable[[TailoredCV, Path, str], Path],
        out_dir: Path,
        min_score: int,
        limit: int,
        budget_seconds: float | None = None,
        cv_en: CVMaster | dict[str, CVMaster] | None = None,
    ) -> None:
        """CV ajustado (PDF) e carta para as melhores vagas da fila que ainda não têm.

        Vaga em inglês usa ``cv_en`` (mesmos IDs do mestre) quando existe; senão o mestre.

        Seleção do CV rejeitada pelo validador: tenta de novo uma vez com o motivo, depois
        usa o CV mestre sem ajuste. Carta rejeitada: tenta de novo uma vez, depois fica sem.
        """
        self.log(f"CV ajustado + carta ({llm.model}, nota >= {min_score}, até {limit})")
        self.start_budget(budget_seconds)
        self._progress("documentos")
        with self.sessions() as s:
            ids = [sc.job_id for sc in DocumentsRepository(s).needing_documents(min_score, limit)]
        for n, job_id in enumerate(ids, 1):
            self._check_stop()
            if self._time_up(len(ids) - n + 1, "documents_deferred"):
                break
            with self.sessions() as s:
                job = to_posting(s.get_one(Job, job_id))
            self._progress("documentos", f"[{n}/{len(ids)}] {job.title} — {job.company_name}")

            lang = job_language(job)
            cv_pt = pick(per_stack(cv), job.stack)
            en = pick(per_stack(cv_en), job.stack) if cv_en else None
            base, doc_lang = (en, "en") if lang == "en" and en else (cv_pt, "pt")
            tailored = self._tailor(llm, base, job, doc_lang)
            folder = out_dir / f"{job_id}-{slugify(job.company_name)}"
            folder.mkdir(parents=True, exist_ok=True)
            clear_cv_variants(folder, profile.short_name, job.stack, doc_lang)
            name = cv_filename(profile.short_name, job.stack, doc_lang)
            pdf = render(tailored, folder / name, doc_lang)
            letter = self._letter(llm, profile, base, job)

            with self.sessions.begin() as s:
                DocumentsRepository(s).save_documents(job_id, pdf, letter)
            self._count("documents")
            suffix = "" if letter else "  (sem carta)"
            self.log(f"  [{n}/{len(ids)}] {job.title} — {job.company_name}{suffix}")

    def _two_tries[T](self, what: str, label: str, attempt: Callable[[str], T]) -> T | None:
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
        self._error(f"{what} em '{label}': {last}")
        return None

    def _tailor(
        self, llm: LLMProvider, cv: CVMaster, job: JobPosting, lang: str = "pt"
    ) -> TailoredCV:
        def attempt(feedback: str) -> TailoredCV:
            prompt = tailor_prompt(cv, job, lang) + feedback
            sel = llm.complete_json(TAILOR_SYSTEM, prompt, CVSelection)
            return apply_selection(cv, sel)

        return self._two_tries("seleção do CV", job.title, attempt) or default_cv(cv)

    def _letter(
        self, llm: LLMProvider, profile: Profile, cv: CVMaster, job: JobPosting
    ) -> CoverLetter | None:
        prompt = letter_prompt(profile, cv, job, job_language(job))

        def attempt(feedback: str) -> CoverLetter:
            letter = llm.complete_json(LETTER_SYSTEM, prompt + feedback, CoverLetter)
            return validate_letter(letter, profile, cv, job)

        return self._two_tries("carta", job.title, attempt)

    def discover_contacts(self, finder, limit: int = 1000) -> None:
        """Varre o site das empresas (nunca varridas ou há mais de 30 dias) atrás do e-mail
        público de recrutamento, da página de carreiras e de uma descrição."""
        self.log("contatos públicos das empresas")
        self._progress("contatos")
        with self.sessions() as s:
            todo = [
                (c.id, c.name, c.website) for c in OutreachRepository(s).needing_discovery(limit)
            ]
        for n, (company_id, name, website) in enumerate(todo, 1):
            self._check_stop()
            self._progress("contatos", f"[{n}/{len(todo)}] {name}")
            found = finder.discover(website)
            with self.sessions.begin() as s:
                company = s.get_one(Company, company_id)
                OutreachRepository(s).save_discovery(
                    company, found.contact, found.source_url, found.careers_url, found.about
                )
            self._count("companies_checked")
            if found.contact:
                self._count("contacts_found")
                self.log(f"  {name}: {found.contact}")
        if todo:
            found_n = self.stats.get("contacts_found", 0)
            self.log(f"  {len(todo)} site(s) varrido(s), {found_n} e-mail(s) de RH")

    def outreach(
        self,
        llm: LLMProvider,
        profile: Profile,
        cv: CVMaster,
        daily_limit: int,
        budget_seconds: float | None = None,
    ) -> None:
        """Escreve e-mails de outreach para até ``daily_limit``
        empresas por dia. Nada é enviado: tudo fica no painel esperando você."""
        self.start_budget(budget_seconds)
        self._progress("outreach")
        with self.sessions() as s:
            repo = OutreachRepository(s)
            room = daily_limit - repo.generated_today()
            todo = [(c.id, c.name, c.sector, c.about) for c in repo.candidates(max(room, 0))]
        self.log(f"outreach ({llm.model}, {len(todo)} empresa(s), limite {daily_limit}/dia)")
        for n, (company_id, name, sector, about) in enumerate(todo, 1):
            self._check_stop()
            if self._time_up(len(todo) - n + 1, "outreach_deferred"):
                break
            self._progress("outreach", f"[{n}/{len(todo)}] {name}")
            prompt = outreach_prompt(profile, cv, name, sector, about)

            def attempt(feedback: str, prompt=prompt, about=about, name=name):
                msg = llm.complete_json(OUTREACH_SYSTEM, prompt + feedback, OutreachMessage)
                return validate_outreach(msg, profile, cv, about, name)

            msg = self._two_tries("outreach", name, attempt)
            if msg is None:
                continue
            with self.sessions.begin() as s:
                OutreachRepository(s).save_message(s.get_one(Company, company_id), msg)
            self._count("outreach")
            self.log(f"  [{n}/{len(todo)}] {name}")

    # ------------------------------------------------------------- orquestração

    def run(self, steps: Sequence[Callable[[], None]]) -> Run:
        """Executa as etapas registrando um ``Run``. Nunca propaga ``Stopped``."""
        self.stats.clear()
        self.errors.clear()
        self.deadline = None
        self.budget_ends_at = None
        with self.sessions.begin() as s:
            repo = JobRepository(s)
            if repo.mark_interrupted_runs():
                self.log("execução anterior foi interrompida; continuando de onde parou")
            run = repo.start_run()
            run.log_path = self.log_path
            run_id = run.id
        self.run_id = run_id
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
                run.current_item = None
            self.run_id = None
        with self.sessions() as s:
            return s.get_one(Run, run_id)
