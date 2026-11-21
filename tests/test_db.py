import pytest
from alembic.autogenerate import compare_metadata
from alembic.runtime.migration import MigrationContext
from sqlalchemy import select

from night_shift.adapters.storage import db
from night_shift.adapters.storage.models import Application, Base, Job
from night_shift.domain.enums import ApplicationStatus, RiskLevel, Source, WorkModel


@pytest.fixture
def engine(paths):
    db.upgrade(paths.db_url)
    engine = db.make_engine(paths.db_url)
    yield engine
    engine.dispose()


def test_upgrade_reaches_head(engine):
    assert db.current_revision(engine) == db.head_revision()


def test_migrations_match_models(engine):
    """Falha se alguém mudou models.py sem gerar migration."""
    with engine.connect() as conn:
        diff = compare_metadata(MigrationContext.configure(conn), Base.metadata)
    assert diff == []


def test_downgrade_to_base_and_back(paths, engine):
    db.upgrade(paths.db_url)  # idempotente
    from alembic import command

    command.downgrade(db.alembic_config(paths.db_url), "base")
    assert db.current_revision(engine) is None
    db.upgrade(paths.db_url)
    assert db.current_revision(engine) == db.head_revision()


def test_enums_roundtrip_as_values(engine):
    Session = db.make_session_factory(engine)
    with Session.begin() as s:
        job = Job(
            source=Source.GUPY,
            external_id="123",
            company_name="Fintech X",
            title="Backend Python Pleno",
            description="...",
            work_model=WorkModel.REMOTO,
            url="https://example.com/vaga/123",
            content_hash="abc",
        )
        s.add(job)
        s.flush()
        s.add(Application(job_id=job.id, risk=RiskLevel.MEDIUM))

    with Session() as s:
        app = s.scalars(select(Application)).one()
        assert app.status is ApplicationStatus.QUEUED
        assert app.job.source is Source.GUPY

    with engine.connect() as conn:
        raw = conn.exec_driver_sql("SELECT source, work_model FROM jobs").one()
    assert tuple(raw) == ("gupy", "remoto")


def test_job_unique_per_source_and_external_id(engine):
    from sqlalchemy.exc import IntegrityError

    Session = db.make_session_factory(engine)
    common = dict(
        source=Source.LEVER,
        external_id="dup",
        company_name="X",
        title="t",
        description="d",
        url="u",
        content_hash="h",
    )
    with Session.begin() as s:
        s.add(Job(**common))
    with pytest.raises(IntegrityError), Session.begin() as s:
        s.add(Job(**common))
