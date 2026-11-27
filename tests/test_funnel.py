"""Funil: histórico automático de etapas, conversões, anotações e a aba no painel."""

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from night_shift.adapters.storage import db
from night_shift.adapters.storage.funnel import FunnelRepository
from night_shift.adapters.storage.models import Application, ApplicationEvent, Job
from night_shift.domain.enums import ApplicationStatus, RiskLevel, Source
from night_shift.web.app import create_app

HX = {"HX-Request": "true"}
S = ApplicationStatus


@pytest.fixture
def sessions(paths):
    db.upgrade(paths.db_url)
    engine = db.make_engine(paths.db_url)
    yield db.make_session_factory(engine)
    engine.dispose()


def add_app(s, ext, *statuses, source=Source.GREENHOUSE):
    job = Job(
        source=source,
        external_id=ext,
        company_name=f"Empresa {ext}",
        title=f"Vaga {ext}",
        description="d",
        url=f"https://x/{ext}",
        content_hash=ext,
    )
    s.add(job)
    s.flush()
    app = Application(job_id=job.id, risk=RiskLevel.LOW)
    s.add(app)
    for status in statuses:
        app.status = status
    s.flush()
    return job.id


def test_every_status_change_becomes_an_event(sessions):
    with sessions.begin() as s:
        job_id = add_app(s, "a", S.APPLIED_MANUAL, S.REPLIED, S.REPLIED, S.INTERVIEW)
    with sessions() as s:
        app = s.scalars(select(Application).where(Application.job_id == job_id)).one()
        assert [e.status for e in app.events] == [S.APPLIED_MANUAL, S.REPLIED, S.INTERVIEW]


def test_conversions_use_history_and_split_by_source(sessions):
    with sessions.begin() as s:
        add_app(s, "a", S.APPLIED_MANUAL)
        add_app(s, "b", S.APPLIED_MANUAL, S.REPLIED)
        add_app(s, "c", S.APPLIED_MANUAL, S.REPLIED, S.INTERVIEW, S.REJECTED)
        add_app(s, "d", S.AUTO_APPLIED, S.REPLIED, S.INTERVIEW, S.OFFER, source=Source.LEVER)
        add_app(s, "e", S.DISCARDED)  # não entra no funil
    with sessions() as s:
        total, greenhouse, lever = FunnelRepository(s).conversions()
    assert total.reached == [4, 3, 2, 1], "a recusada depois da entrevista conta a entrevista"
    assert total.rate(0) == 75 and total.rate(1) == 67 and total.rate(2) == 50
    assert (greenhouse.label, greenhouse.reached) == ("greenhouse", [3, 2, 1, 0])
    assert (lever.label, lever.reached) == ("lever", [1, 1, 1, 1])


def test_board_moves_and_notes(sessions):
    with sessions.begin() as s:
        job_id = add_app(s, "a", S.APPLIED_MANUAL)
        repo = FunnelRepository(s)
        repo.move(job_id, "resposta")
        repo.add_note(job_id, "  falei com a recrutadora  ")
        with pytest.raises(KeyError):
            repo.move(job_id, "contratado")
    with sessions() as s:
        repo = FunnelRepository(s)
        board = repo.board()
        assert [a.job_id for a in board["resposta"]] == [job_id] and board["aplicadas"] == []
        assert [n.text for n in repo.notes([job_id])[job_id]] == ["falei com a recrutadora"]


def test_migration_backfills_events_for_existing_applications(paths):
    from alembic import command

    cfg = db.alembic_config(paths.db_url)
    command.upgrade(cfg, "cb66e58d4351")  # antes do funil
    engine = db.make_engine(paths.db_url)
    with engine.begin() as conn:
        conn.exec_driver_sql(
            "INSERT INTO jobs (source, external_id, company_name, title, description, url,"
            " content_hash, collected_at) VALUES ('gupy','1','X','T','d','u','h','2026-11-01')"
        )
        conn.exec_driver_sql(
            "INSERT INTO applications (job_id, status, risk, applied_at, created_at, updated_at)"
            " VALUES (1, 'applied_manual', 'medium', '2026-11-02', '2026-11-01', '2026-11-02')"
        )
    command.upgrade(cfg, "head")
    with db.make_session_factory(engine)() as s:
        [event] = s.scalars(select(ApplicationEvent)).all()
        assert event.status is S.APPLIED_MANUAL and event.at.day == 2
    engine.dispose()


def test_funnel_page_move_and_note(sessions):
    with sessions.begin() as s:
        job_id = add_app(s, "a", S.APPLIED_MANUAL)
    client = TestClient(create_app(sessions))

    html = client.get("/funil").text
    assert "Vaga a" in html and "Teve resposta" in html and ">Funil</a>" in html

    assert client.post(f"/funil/{job_id}/mover/resposta").status_code == 403
    resp = client.post(f"/funil/{job_id}/mover/resposta", headers=HX)
    moved = resp.text
    assert "Entrevista marcada" in moved, "card agora na coluna Resposta"
    assert '"message": "Vaga a: resposta"' in resp.headers["HX-Trigger"]
    assert "<b>1</b><span>resposta</span>" in moved

    noted = client.post(f"/jobs/{job_id}/notas", data={"texto": "entrevista dia 5"}, headers=HX)
    assert "entrevista dia 5" in noted.text and "Anotações (1)" in noted.text
    assert (
        client.post(f"/jobs/{job_id}/notas", data={"texto": "   "}, headers=HX).status_code == 422
    )
    assert client.post(f"/funil/{job_id}/mover/xyz", headers=HX).status_code == 404
    assert client.post("/funil/999/mover/resposta", headers=HX).status_code == 404
    assert client.post("/jobs/999/notas", data={"texto": "x"}, headers=HX).status_code == 404
