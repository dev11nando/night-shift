from collections.abc import Sequence
from datetime import datetime

from sqlalchemy import exists, select
from sqlalchemy.orm import Session

from night_shift.adapters.storage.models import Application, Company, Job, Run, Score, utcnow
from night_shift.config import CompanyConfig
from night_shift.domain.enrich import enrich
from night_shift.domain.enums import ApplicationStatus, RunStatus
from night_shift.domain.job import JobPosting


def to_posting(job: Job) -> JobPosting:
    return JobPosting(
        source=job.source,
        external_id=job.external_id,
        company_name=job.company_name,
        title=job.title,
        description=job.description,
        url=job.url,
        location=job.location,
        work_model=job.work_model,
        contract=job.contract,
        level=job.level,
        salary_min=job.salary_min,
        salary_max=job.salary_max,
        published_at=job.published_at,
    )


class JobRepository:
    def __init__(self, session: Session) -> None:
        self.s = session

    # ---------------------------------------------------------------- companies

    def sync_companies(self, configs: Sequence[CompanyConfig]) -> dict[str, int]:
        """Upsert por nome. Retorna ``{nome: id}``."""
        existing = {c.name: c for c in self.s.scalars(select(Company))}
        for cfg in configs:
            row = existing.get(cfg.name) or Company(name=cfg.name)
            row.sector, row.website = cfg.sector, cfg.website
            row.ats, row.ats_slug = cfg.ats, cfg.slug
            row.outreach_contact = cfg.outreach_contact
            self.s.add(row)
            existing[cfg.name] = row
        self.s.flush()
        return {name: c.id for name, c in existing.items()}

    # --------------------------------------------------------------------- jobs

    def add_if_new(self, posting: JobPosting, company_id: int | None) -> bool:
        """Insere a vaga se ainda não existe (mesma fonte+id ou mesmo conteúdo)."""
        dup = self.s.scalar(
            select(
                exists().where(
                    ((Job.source == posting.source) & (Job.external_id == posting.external_id))
                    | (Job.content_hash == posting.content_hash)
                )
            )
        )
        if dup:
            return False
        self.s.add(
            Job(
                source=posting.source,
                external_id=posting.external_id,
                company_id=company_id,
                company_name=posting.company_name,
                title=posting.title,
                description=posting.description,
                location=posting.location,
                work_model=posting.work_model,
                contract=posting.contract,
                level=posting.level,
                salary_min=posting.salary_min,
                salary_max=posting.salary_max,
                url=posting.url,
                content_hash=posting.content_hash,
                published_at=posting.published_at,
            )
        )
        return True

    def enrich_existing(self) -> int:
        """Reaplica ``enrich`` em vagas já gravadas (nível, contrato, salário). Retorna quantas
        mudaram. Útil depois de melhorar a extração."""
        changed = 0
        for job in self.s.scalars(select(Job)):
            enriched = enrich(to_posting(job))
            fields = ("level", "contract", "salary_min", "salary_max")
            if any(getattr(job, f) != getattr(enriched, f) for f in fields):
                for f in fields:
                    setattr(job, f, getattr(enriched, f))
                changed += 1
        return changed

    def unscreened(self) -> Sequence[Job]:
        return self.s.scalars(select(Job).where(~exists().where(Score.job_id == Job.id))).all()

    def save_screening(self, job: Job, reason: str | None) -> None:
        self.s.add(Score(job_id=job.id, filter_reason=reason))

    def needing_similarity(self) -> Sequence[Score]:
        return self.s.scalars(
            select(Score).where(Score.filter_reason.is_(None), Score.embed_similarity.is_(None))
        ).all()

    def top_unscored(self, n: int) -> Sequence[Score]:
        """Melhores por similaridade que ainda não passaram pelo LLM (inclui sobras de
        noites anteriores, que assim não se perdem)."""
        return self.s.scalars(
            select(Score)
            .where(
                Score.filter_reason.is_(None),
                Score.embed_similarity.is_not(None),
                Score.llm_score.is_(None),
            )
            .order_by(Score.embed_similarity.desc())
            .limit(n)
        ).all()

    def save_llm_score(
        self, score: Score, value: int, rationale: str, red_flags: list[str], model: str
    ) -> None:
        score.llm_score, score.rationale = value, rationale
        score.red_flags, score.model, score.scored_at = red_flags, model, utcnow()

    def reset_llm_scores(self) -> int:
        """Apaga as notas do LLM de vagas ainda sem decisão, para reavaliar (ex.: depois de
        mudar o prompt ou o modelo). Decididas (aplicadas/descartadas) ficam como estão."""
        decided = select(Application.job_id).where(Application.status != ApplicationStatus.QUEUED)
        scores = self.s.scalars(
            select(Score).where(Score.llm_score.is_not(None), Score.job_id.not_in(decided))
        ).all()
        for sc in scores:
            sc.llm_score = sc.rationale = sc.model = sc.scored_at = None
            sc.red_flags = []
        return len(scores)

    def ranked(self, limit: int, since: datetime | None = None) -> Sequence[Score]:
        q = select(Score).where(Score.llm_score.is_not(None))
        if since:
            q = q.where(Score.scored_at >= since)
        return self.s.scalars(
            q.order_by(Score.llm_score.desc(), Score.embed_similarity.desc()).limit(limit)
        ).all()

    # --------------------------------------------------------------------- runs

    def mark_interrupted_runs(self) -> int:
        """Execuções que ficaram como ``running`` foram mortas no meio (PC desligado,
        processo encerrado). Como só um pipeline roda por vez, ao começar outro elas viram
        ``failed``. Os dados que já gravaram continuam valendo: as etapas são idempotentes,
        então a nova execução segue de onde aquela parou."""
        stale = self.s.scalars(select(Run).where(Run.status == RunStatus.RUNNING)).all()
        for run in stale:
            run.status = RunStatus.FAILED
            run.errors = [*(run.errors or []), "execução interrompida (processo encerrado)"]
        return len(stale)

    def start_run(self) -> Run:
        run = Run(stats={}, errors=[])
        self.s.add(run)
        self.s.flush()
        return run
