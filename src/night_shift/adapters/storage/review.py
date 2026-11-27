"""Consultas e decisões do painel: fila de revisão, histórico e dados de mercado."""

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, timedelta
from statistics import median

from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session, joinedload

from night_shift.adapters.storage.models import Application, Job, Run, Score, utcnow
from night_shift.domain.enums import SOURCE_RISK, ApplicationStatus, Contract, Level
from night_shift.domain.lanes import Lane, lane_for
from night_shift.domain.text import fold

ORDERS = ("nota", "recentes", "empresa")
APPLIED = (ApplicationStatus.APPLIED_MANUAL, ApplicationStatus.AUTO_APPLIED)


@dataclass(frozen=True)
class QueueCounts:
    auto: int
    manual: int
    applied: int
    discarded: int

    @property
    def queued(self) -> int:
        return self.auto + self.manual


@dataclass(frozen=True)
class SalaryBucket:
    level: Level | None
    contract: Contract | None
    count: int
    median_min: int | None
    median_max: int | None


class ReviewRepository:
    def __init__(self, session: Session, auto_threshold: int = 85) -> None:
        self.s = session
        self.auto_threshold = auto_threshold

    def lane(self, sc: Score) -> Lane:
        return lane_for(sc.job.source, sc.llm_score, sc.red_flags or [], self.auto_threshold)

    def _scored(self):
        return (
            select(Score)
            .join(Score.job)
            .outerjoin(Application, Application.job_id == Job.id)
            .options(joinedload(Score.job).joinedload(Job.application))
            .where(Score.llm_score.is_not(None))
        )

    def _pending(self, min_score: int = 0) -> Sequence[Score]:
        q = self._scored().where(
            Score.llm_score >= min_score,
            or_(Application.id.is_(None), Application.status == ApplicationStatus.QUEUED),
        )
        return (
            self.s.scalars(q.order_by(Score.llm_score.desc(), Score.embed_similarity.desc()))
            .unique()
            .all()
        )

    def queue(
        self,
        lane: Lane | None = None,
        min_score: int = 0,
        limit: int = 100,
        stack: str | None = None,
        search: str = "",
        order: str = "nota",
    ) -> list[Score]:
        """Vagas avaliadas ainda sem decisão, opcionalmente só de uma fila, de uma stack e
        com ``search`` no cargo ou na empresa (sem acento, sem caixa). Ordem: ``nota`` (maior
        primeiro), ``recentes`` (coletadas por último) ou ``empresa`` (A a Z). A fila é
        calculada na hora, então o filtro é em Python."""
        pending = list(self._pending(min_score))
        if lane is not None:
            pending = [sc for sc in pending if self.lane(sc) is lane]
        if stack:
            pending = [sc for sc in pending if sc.job.stack == stack]
        if terms := fold(search).split():
            pending = [
                sc
                for sc in pending
                if all(t in fold(f"{sc.job.title} {sc.job.company_name}") for t in terms)
            ]
        if order == "recentes":
            pending.sort(key=lambda sc: sc.job.collected_at, reverse=True)
        elif order == "empresa":
            pending.sort(key=lambda sc: (fold(sc.job.company_name), -(sc.llm_score or 0)))
        return pending[:limit]

    def fresh_best(self, days: int = 7, limit: int = 5) -> list[Score]:
        """Melhores vagas da fila que receberam nota nos últimos ``days`` dias."""
        since = utcnow() - timedelta(days=days)
        fresh = [sc for sc in self._pending() if sc.scored_at and _aware(sc.scored_at) >= since]
        return fresh[:limit]

    def awaiting_reply(self, days: int = 7) -> list[Application]:
        """Candidaturas enviadas há ``days`` dias ou mais que continuam sem resposta: hora
        de cobrar."""
        cutoff = utcnow() - timedelta(days=days)
        apps = self.s.scalars(
            select(Application)
            .options(joinedload(Application.job))
            .where(Application.status.in_(APPLIED))
        ).all()
        return sorted(
            (a for a in apps if _aware(a.applied_at or a.updated_at) <= cutoff),
            key=lambda a: a.applied_at or a.updated_at,
        )

    def decided(self, statuses: tuple[ApplicationStatus, ...], limit: int = 100) -> Sequence[Score]:
        q = self._scored().where(Application.status.in_(statuses))
        return self.s.scalars(q.order_by(Application.updated_at.desc()).limit(limit)).unique().all()

    def counts(self) -> QueueCounts:
        by_status = dict(
            self.s.execute(
                select(Application.status, func.count()).group_by(Application.status)
            ).all()
        )
        lanes = [self.lane(sc) for sc in self._pending()]
        return QueueCounts(
            auto=lanes.count(Lane.AUTO),
            manual=lanes.count(Lane.MANUAL),
            applied=by_status.get(ApplicationStatus.APPLIED_MANUAL, 0)
            + by_status.get(ApplicationStatus.AUTO_APPLIED, 0),
            discarded=by_status.get(ApplicationStatus.DISCARDED, 0),
        )

    def decide(self, job_id: int, status: ApplicationStatus) -> Score:
        """Marca a vaga como aplicada à mão ou descartada (idempotente)."""
        job = self.s.get_one(Job, job_id)
        app = job.application or Application(job_id=job.id, risk=SOURCE_RISK[job.source])
        app.status = status
        app.applied_at = utcnow() if status is ApplicationStatus.APPLIED_MANUAL else None
        self.s.add(app)
        self.s.flush()
        return job.score

    def undo(self, job_id: int) -> Score:
        """Devolve a vaga para a fila."""
        job = self.s.get_one(Job, job_id)
        if job.application is not None:
            job.application.status = ApplicationStatus.QUEUED
            job.application.applied_at = None
            self.s.flush()
        return job.score

    def recent_runs(self, limit: int = 5) -> Sequence[Run]:
        return self.s.scalars(select(Run).order_by(Run.started_at.desc()).limit(limit)).all()

    def latest_run(self) -> Run | None:
        return self.s.scalars(select(Run).order_by(Run.id.desc()).limit(1)).first()

    def scored_since(self, since, limit: int = 8) -> Sequence[Score]:
        """Notas dadas a partir de ``since``, as mais recentes primeiro (feed ao vivo)."""
        q = self._scored().where(Score.scored_at >= since)
        return self.s.scalars(q.order_by(Score.scored_at.desc()).limit(limit)).unique().all()

    def best_of_run(self, run: Run, limit: int = 5) -> Sequence[Score]:
        """Melhores notas dadas durante uma execução."""
        q = self._scored().where(Score.scored_at >= run.started_at)
        if run.finished_at:
            q = q.where(Score.scored_at <= run.finished_at)
        return self.s.scalars(q.order_by(Score.llm_score.desc()).limit(limit)).unique().all()

    def salary_buckets(self) -> list[SalaryBucket]:
        """Mediana das faixas publicadas, agrupada por nível e contrato."""
        rows = self.s.execute(
            select(Job.level, Job.contract, Job.salary_min, Job.salary_max).where(
                or_(Job.salary_min.is_not(None), Job.salary_max.is_not(None))
            )
        ).all()
        groups: dict[tuple, list[tuple[int | None, int | None]]] = {}
        for level, contract, lo, hi in rows:
            groups.setdefault((level, contract), []).append((lo, hi))

        def med(values: list[int | None]) -> int | None:
            present = [v for v in values if v is not None]
            return round(median(present)) if present else None

        order = {Level.JUNIOR: 0, Level.PLENO: 1, Level.SENIOR: 2, None: 3}
        return sorted(
            (
                SalaryBucket(
                    level,
                    contract,
                    len(vals),
                    med([lo for lo, _ in vals]),
                    med([hi for _, hi in vals]),
                )
                for (level, contract), vals in groups.items()
            ),
            key=lambda b: (order[b.level], str(b.contract)),
        )

    def jobs_with_salary(self, limit: int = 200) -> Sequence[Job]:
        return self.s.scalars(
            select(Job)
            .where(or_(Job.salary_min.is_not(None), Job.salary_max.is_not(None)))
            .order_by(Job.salary_min.desc().nulls_last())
            .limit(limit)
        ).all()


def _aware(value):
    """O SQLite devolve datetime sem fuso; gravamos sempre em UTC."""
    return value if value.tzinfo else value.replace(tzinfo=UTC)
