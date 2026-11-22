"""Funil das candidaturas: aplicada → resposta → entrevista → proposta (ou recusada)."""

from collections import defaultdict
from collections.abc import Sequence
from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.orm import Session, joinedload

from night_shift.adapters.storage.models import Application, Job, JobNote, Outreach
from night_shift.domain.enums import ApplicationStatus, OutreachStatus

APPLIED = (ApplicationStatus.APPLIED_MANUAL, ApplicationStatus.AUTO_APPLIED)

# (chave, rótulo, status que contam como "estar nesta etapa")
STAGES: list[tuple[str, str, tuple[ApplicationStatus, ...]]] = [
    ("aplicadas", "Aplicadas", APPLIED),
    ("resposta", "Resposta", (ApplicationStatus.REPLIED,)),
    ("entrevista", "Entrevista", (ApplicationStatus.INTERVIEW,)),
    ("proposta", "Proposta", (ApplicationStatus.OFFER,)),
]
REJECTED = ("recusadas", "Recusadas", (ApplicationStatus.REJECTED,))
FUNNEL_STATUSES = (
    *APPLIED,
    *(s for _, _, ss in STAGES[1:] for s in ss),
    ApplicationStatus.REJECTED,
)

# Para onde cada botão do card move a candidatura.
MOVES = {
    "resposta": ApplicationStatus.REPLIED,
    "entrevista": ApplicationStatus.INTERVIEW,
    "proposta": ApplicationStatus.OFFER,
    "recusada": ApplicationStatus.REJECTED,
    "aplicada": ApplicationStatus.APPLIED_MANUAL,
}


def stage_index(status: ApplicationStatus) -> int | None:
    for i, (_, _, statuses) in enumerate(STAGES):
        if status in statuses:
            return i
    return None


@dataclass(frozen=True)
class Conversion:
    label: str
    reached: list[int]  # quantas chegaram a cada etapa (Aplicadas, Resposta, ...)

    def rate(self, i: int) -> int | None:
        """% que passou da etapa i para a i+1."""
        if self.reached[i] == 0:
            return None
        return round(100 * self.reached[i + 1] / self.reached[i])


class FunnelRepository:
    def __init__(self, session: Session) -> None:
        self.s = session

    def _apps(self) -> Sequence[Application]:
        return (
            self.s.scalars(
                select(Application)
                .options(joinedload(Application.job), joinedload(Application.events))
                .where(Application.status.in_(FUNNEL_STATUSES))
                .order_by(Application.updated_at.desc())
            )
            .unique()
            .all()
        )

    def board(self) -> dict[str, list[Application]]:
        """Candidaturas agrupadas pela etapa atual."""
        columns: dict[str, list[Application]] = {key: [] for key, _, _ in [*STAGES, REJECTED]}
        for app in self._apps():
            for key, _, statuses in [*STAGES, REJECTED]:
                if app.status in statuses:
                    columns[key].append(app)
        return columns

    def conversions(self) -> list[Conversion]:
        """Quantas chegaram a cada etapa (pelo histórico: recusada depois de entrevista
        conta como tendo chegado à entrevista), no total e por fonte."""
        by_label: dict[str, list[int]] = defaultdict(lambda: [0] * len(STAGES))
        for app in self._apps():
            reached = [stage_index(e.status) for e in app.events]
            reached.append(stage_index(app.status))
            best = max((r for r in reached if r is not None), default=None)
            if best is None:
                continue
            for label in ("Total", f"{app.job.source}"):
                for i in range(best + 1):
                    by_label[label][i] += 1
        rows = [Conversion("Total", by_label.pop("Total", [0] * len(STAGES)))]
        rows += [Conversion(label, counts) for label, counts in sorted(by_label.items())]
        return rows

    def outreach_stats(self) -> tuple[int, int]:
        """(enviadas, responderam) do outreach."""
        statuses = list(
            self.s.scalars(
                select(Outreach.status).where(
                    Outreach.status.in_([OutreachStatus.SENT, OutreachStatus.REPLIED])
                )
            )
        )
        return len(statuses), statuses.count(OutreachStatus.REPLIED)

    def move(self, job_id: int, to: str) -> Application:
        if to not in MOVES:
            raise KeyError(to)
        app = self.s.scalars(select(Application).where(Application.job_id == job_id)).one()
        app.status = MOVES[to]
        self.s.flush()
        return app

    def add_note(self, job_id: int, text: str) -> JobNote:
        self.s.get_one(Job, job_id)
        note = JobNote(job_id=job_id, text=text.strip())
        self.s.add(note)
        self.s.flush()
        return note

    def notes(self, job_ids: list[int]) -> dict[int, list[JobNote]]:
        out: dict[int, list[JobNote]] = defaultdict(list)
        if job_ids:
            for note in self.s.scalars(
                select(JobNote).where(JobNote.job_id.in_(job_ids)).order_by(JobNote.created_at)
            ):
                out[note.job_id].append(note)
        return out
