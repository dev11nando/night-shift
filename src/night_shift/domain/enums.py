from enum import StrEnum


class Level(StrEnum):
    JUNIOR = "junior"
    PLENO = "pleno"
    SENIOR = "senior"


class WorkModel(StrEnum):
    REMOTO = "remoto"
    HIBRIDO = "hibrido"
    PRESENCIAL = "presencial"


class Contract(StrEnum):
    CLT = "clt"
    PJ = "pj"


class Source(StrEnum):
    GREENHOUSE = "greenhouse"
    LEVER = "lever"
    ASHBY = "ashby"
    GUPY = "gupy"
    PROGRAMATHOR = "programathor"
    LINKEDIN_ALERTS = "linkedin_alerts"


class RiskLevel(StrEnum):
    """Risco de automatizar a candidatura numa fonte (ver docs/ESCOPO.md §4)."""

    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


SOURCE_RISK: dict[Source, RiskLevel] = {
    Source.GREENHOUSE: RiskLevel.LOW,
    Source.LEVER: RiskLevel.LOW,
    Source.ASHBY: RiskLevel.LOW,
    Source.PROGRAMATHOR: RiskLevel.MEDIUM,
    Source.GUPY: RiskLevel.MEDIUM,
    Source.LINKEDIN_ALERTS: RiskLevel.HIGH,
}


class ApplicationStatus(StrEnum):
    QUEUED = "queued"
    AUTO_APPLIED = "auto_applied"
    APPLIED_MANUAL = "applied_manual"
    DISCARDED = "discarded"
    REPLIED = "replied"
    INTERVIEW = "interview"
    OFFER = "offer"
    REJECTED = "rejected"


class OutreachStatus(StrEnum):
    DRAFT = "draft"  # escrito, esperando você aprovar no painel
    SENT = "sent"
    REPLIED = "replied"
    DISCARDED = "discarded"


class RunStatus(StrEnum):
    RUNNING = "running"
    SUCCESS = "success"
    FAILED = "failed"
    STOPPED = "stopped"
