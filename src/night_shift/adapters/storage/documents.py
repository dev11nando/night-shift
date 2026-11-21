from collections.abc import Sequence
from pathlib import Path

from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from night_shift.adapters.storage.models import Application, Job, Score
from night_shift.application.documents import CoverLetter
from night_shift.domain.enums import SOURCE_RISK, ApplicationStatus


class DocumentsRepository:
    def __init__(self, session: Session) -> None:
        self.s = session

    def needing_documents(self, min_score: int, limit: int) -> Sequence[Score]:
        """Vagas da fila (sem decisão) com nota suficiente e ainda sem CV ajustado."""
        q = (
            select(Score)
            .join(Score.job)
            .outerjoin(Application, Application.job_id == Job.id)
            .where(
                Score.llm_score >= min_score,
                or_(
                    Application.id.is_(None),
                    (Application.status == ApplicationStatus.QUEUED)
                    & Application.cv_variant_path.is_(None),
                ),
            )
            .order_by(Score.llm_score.desc(), Score.embed_similarity.desc())
            .limit(limit)
        )
        return self.s.scalars(q).all()

    def save_documents(self, job_id: int, cv_path: Path, letter: CoverLetter | None) -> None:
        job = self.s.get_one(Job, job_id)
        app = job.application or Application(
            job_id=job.id, risk=SOURCE_RISK[job.source], status=ApplicationStatus.QUEUED
        )
        app.cv_variant_path = str(cv_path)
        app.cover_letter = letter.body if letter else None
        app.answers = {**(app.answers or {}), "letter_subject": letter.subject if letter else None}
        self.s.add(app)

    def clear_documents(self) -> int:
        """Apaga CV ajustado e carta de vagas ainda na fila, para gerar de novo."""
        apps = self.s.scalars(
            select(Application).where(
                Application.status == ApplicationStatus.QUEUED,
                Application.cv_variant_path.is_not(None),
            )
        ).all()
        for app in apps:
            app.cv_variant_path = app.cover_letter = None
        return len(apps)
