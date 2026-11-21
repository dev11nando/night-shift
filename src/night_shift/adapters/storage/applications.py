from collections.abc import Sequence

from sqlalchemy import select
from sqlalchemy.orm import Session

from night_shift.adapters.storage.models import Application, Job, Score, utcnow
from night_shift.adapters.storage.review import ReviewRepository
from night_shift.domain.enums import SOURCE_RISK, ApplicationStatus, RiskLevel
from night_shift.domain.lanes import Lane


class ApplyRepository:
    def __init__(self, session: Session, auto_threshold: int) -> None:
        self.s = session
        self.review = ReviewRepository(session, auto_threshold)

    def ready(self, limit: int) -> list[Score]:
        """Fila automática com CV ajustado pronto, da maior nota para a menor."""
        return [
            sc
            for sc in self.review.queue(Lane.AUTO, limit=10_000)
            if sc.job.application is not None and sc.job.application.cv_variant_path
        ][:limit]

    def one(self, job_id: int) -> Score | None:
        """Qualquer vaga de fonte de baixo risco (para aplicar algo da fila manual)."""
        sc = self.s.scalar(select(Score).where(Score.job_id == job_id))
        if sc is None or SOURCE_RISK[sc.job.source] is not RiskLevel.LOW:
            return None
        return sc

    def applied_today(self) -> int:
        today = utcnow().replace(hour=0, minute=0, second=0, microsecond=0)
        return len(
            self.s.scalars(
                select(Application.id).where(
                    Application.status == ApplicationStatus.AUTO_APPLIED,
                    Application.applied_at >= today,
                )
            ).all()
        )

    def save_outcome(self, job_id: int, outcome: dict, *, applied: bool) -> None:
        job = self.s.get_one(Job, job_id)
        app = job.application or Application(job_id=job.id, risk=SOURCE_RISK[job.source])
        history = [*((app.answers or {}).get("apply_history") or []), outcome]
        app.answers = {**(app.answers or {}), "apply": outcome, "apply_history": history[-5:]}
        if applied:
            app.status = ApplicationStatus.AUTO_APPLIED
            app.applied_at = utcnow()
        self.s.add(app)

    def pending(self) -> Sequence[Score]:
        return self.review.queue(Lane.AUTO, limit=10_000)
