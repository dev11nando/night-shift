"""Tabelas SQLite (docs/ESCOPO.md §7). Mudou algo aqui? Gere uma migration:

uv run alembic revision --autogenerate -m "descricao"
"""

from datetime import UTC, datetime
from enum import StrEnum
from typing import Any

from sqlalchemy import JSON, Enum, ForeignKey, MetaData, String, Text, UniqueConstraint
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship

from night_shift.domain.enums import (
    ApplicationStatus,
    Contract,
    Level,
    OutreachStatus,
    RiskLevel,
    RunStatus,
    Source,
    WorkModel,
)

NAMING_CONVENTION = {
    "ix": "ix_%(column_0_label)s",
    "uq": "uq_%(table_name)s_%(column_0_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s",
}


def utcnow() -> datetime:
    return datetime.now(UTC)


def str_enum(enum_cls: type[StrEnum]) -> Enum:
    """Enum guardado como VARCHAR com o *valor* (``"queued"``), não o nome do membro."""
    return Enum(
        enum_cls,
        native_enum=False,
        length=20,
        values_callable=lambda e: [m.value for m in e],
        validate_strings=True,
    )


class Base(DeclarativeBase):
    metadata = MetaData(naming_convention=NAMING_CONVENTION)


class Company(Base):
    __tablename__ = "companies"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(200), unique=True)
    sector: Mapped[str | None] = mapped_column(String(50))
    website: Mapped[str | None] = mapped_column(String(500))
    ats: Mapped[str | None] = mapped_column(String(30))
    ats_slug: Mapped[str | None] = mapped_column(String(200))
    outreach_contact: Mapped[str | None] = mapped_column(String(320))
    # Página do próprio site da empresa onde o e-mail público de RH foi encontrado.
    contact_source_url: Mapped[str | None] = mapped_column(String(500))
    careers_url: Mapped[str | None] = mapped_column(String(500))
    contact_checked_at: Mapped[datetime | None]
    about: Mapped[str | None] = mapped_column(Text)
    last_contacted_at: Mapped[datetime | None]
    created_at: Mapped[datetime] = mapped_column(default=utcnow)

    jobs: Mapped[list["Job"]] = relationship(back_populates="company")


class Job(Base):
    __tablename__ = "jobs"
    __table_args__ = (UniqueConstraint("source", "external_id", name="uq_jobs_source_external"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    source: Mapped[Source] = mapped_column(str_enum(Source))
    external_id: Mapped[str] = mapped_column(String(200))
    company_id: Mapped[int | None] = mapped_column(ForeignKey("companies.id"))
    company_name: Mapped[str] = mapped_column(String(200))
    title: Mapped[str] = mapped_column(String(300))
    description: Mapped[str] = mapped_column(Text)
    location: Mapped[str | None] = mapped_column(String(200))
    work_model: Mapped[WorkModel | None] = mapped_column(str_enum(WorkModel))
    contract: Mapped[Contract | None] = mapped_column(str_enum(Contract))
    level: Mapped[Level | None] = mapped_column(str_enum(Level))
    salary_min: Mapped[int | None]
    salary_max: Mapped[int | None]
    url: Mapped[str] = mapped_column(String(1000))
    content_hash: Mapped[str] = mapped_column(String(64), index=True)
    published_at: Mapped[datetime | None]
    collected_at: Mapped[datetime] = mapped_column(default=utcnow)

    company: Mapped[Company | None] = relationship(back_populates="jobs")
    score: Mapped["Score | None"] = relationship(back_populates="job")
    application: Mapped["Application | None"] = relationship(back_populates="job")


class Score(Base):
    __tablename__ = "scores"

    id: Mapped[int] = mapped_column(primary_key=True)
    job_id: Mapped[int] = mapped_column(ForeignKey("jobs.id"), unique=True)
    # Preenchido quando o filtro por regra cortou a vaga; aí não há similaridade nem nota.
    filter_reason: Mapped[str | None] = mapped_column(String(200))
    embed_similarity: Mapped[float | None]
    llm_score: Mapped[int | None]
    rationale: Mapped[str | None] = mapped_column(Text)
    red_flags: Mapped[list[str]] = mapped_column(JSON, default=list)
    model: Mapped[str | None] = mapped_column(String(100))
    created_at: Mapped[datetime] = mapped_column(default=utcnow)
    scored_at: Mapped[datetime | None]

    job: Mapped[Job] = relationship(back_populates="score")


class Application(Base):
    __tablename__ = "applications"

    id: Mapped[int] = mapped_column(primary_key=True)
    job_id: Mapped[int] = mapped_column(ForeignKey("jobs.id"), unique=True)
    status: Mapped[ApplicationStatus] = mapped_column(
        str_enum(ApplicationStatus), default=ApplicationStatus.QUEUED
    )
    risk: Mapped[RiskLevel] = mapped_column(str_enum(RiskLevel))
    cv_variant_path: Mapped[str | None] = mapped_column(String(500))
    cover_letter: Mapped[str | None] = mapped_column(Text)
    answers: Mapped[dict[str, Any] | None] = mapped_column(JSON)
    applied_at: Mapped[datetime | None]
    created_at: Mapped[datetime] = mapped_column(default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(default=utcnow, onupdate=utcnow)

    job: Mapped[Job] = relationship(back_populates="application")


class Outreach(Base):
    __tablename__ = "outreach"

    id: Mapped[int] = mapped_column(primary_key=True)
    company_id: Mapped[int] = mapped_column(ForeignKey("companies.id"))
    to_address: Mapped[str | None] = mapped_column(String(320))  # None = só LinkedIn
    gmail_draft_id: Mapped[str | None] = mapped_column(String(200))
    subject: Mapped[str] = mapped_column(String(300))
    body: Mapped[str] = mapped_column(Text)  # versão e-mail
    linkedin_note: Mapped[str | None] = mapped_column(String(300))
    status: Mapped[OutreachStatus] = mapped_column(
        str_enum(OutreachStatus), default=OutreachStatus.DRAFT
    )
    created_at: Mapped[datetime] = mapped_column(default=utcnow)
    sent_at: Mapped[datetime | None]

    company: Mapped[Company] = relationship()


class Run(Base):
    __tablename__ = "runs"

    id: Mapped[int] = mapped_column(primary_key=True)
    started_at: Mapped[datetime] = mapped_column(default=utcnow)
    finished_at: Mapped[datetime | None]
    stage: Mapped[str | None] = mapped_column(String(50))
    status: Mapped[RunStatus] = mapped_column(str_enum(RunStatus), default=RunStatus.RUNNING)
    stats: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    errors: Mapped[list[str]] = mapped_column(JSON, default=list)
    # Progresso ao vivo (página /ao-vivo): o que está sendo feito agora e até quando.
    current_item: Mapped[str | None] = mapped_column(String(300))
    budget_ends_at: Mapped[datetime | None]
    log_path: Mapped[str | None] = mapped_column(String(500))
