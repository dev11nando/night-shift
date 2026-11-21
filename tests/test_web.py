from datetime import timedelta

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from night_shift.adapters.storage import db
from night_shift.adapters.storage.models import Application, Job, Run, Score, utcnow
from night_shift.domain.enums import (
    ApplicationStatus,
    Contract,
    Level,
    RiskLevel,
    RunStatus,
    Source,
)
from night_shift.web.app import create_app

HX = {"HX-Request": "true"}


@pytest.fixture
def sessions(paths):
    db.upgrade(paths.db_url)
    engine = db.make_engine(paths.db_url)
    yield db.make_session_factory(engine)
    engine.dispose()


@pytest.fixture
def client(sessions):
    return TestClient(create_app(sessions))


def add_job(s, ext, title, score=None, *, salary=None, level=None, contract=None, source=None):
    job = Job(
        source=source or Source.GREENHOUSE,
        external_id=ext,
        company_name="Fintech X",
        title=title,
        description="Python e FastAPI",
        url=f"https://example.com/{ext}",
        content_hash=ext,
        location="São Paulo",
        salary_min=salary,
        level=level,
        contract=contract,
    )
    s.add(job)
    s.flush()
    s.add(
        Score(
            job_id=job.id,
            embed_similarity=0.8,
            llm_score=score,
            rationale=f"motivo {ext}" if score is not None else None,
            red_flags=["exige inglês fluente"] if score == 55 else [],
            scored_at=utcnow() if score is not None else None,
        )
    )
    return job


@pytest.fixture
def seeded(sessions):
    with sessions.begin() as s:
        run = Run(
            started_at=utcnow() - timedelta(minutes=5),
            stats={"collected": 120, "new": 30, "passed_filter": 8, "llm_scored": 3},
            errors=["gupy: layout mudou"],
            status=RunStatus.SUCCESS,
        )
        s.add(run)
        s.flush()
        ids = {
            "top": add_job(s, "a", "Backend Python Pleno", 91).id,
            "mid": add_job(s, "b", "Desenvolvedor Python", 55).id,
            "low": add_job(s, "c", "Engenheiro de Software", 30).id,
            "unscored": add_job(s, "d", "Ainda sem nota").id,
            "gupy": add_job(s, "e", "Python Gupy", 70, source=Source.GUPY).id,
        }
        add_job(s, "f", "Pleno CLT", None, salary=6000, level=Level.PLENO, contract=Contract.CLT)
        add_job(s, "g", "Pleno CLT 2", None, salary=8000, level=Level.PLENO, contract=Contract.CLT)
        run.finished_at = utcnow()
    return ids


def test_empty_pages_render(client):
    assert "Nenhuma execução ainda" in client.get("/").text
    assert "Nada na fila manual" in client.get("/fila").text
    assert "Nenhuma vaga com salário" in client.get("/mercado").text


def test_hoje_shows_last_run_funnel_errors_and_best(client, seeded):
    html = client.get("/").text
    assert "Última execução" in html
    assert "120" in html and "coletadas" in html
    assert "gupy: layout mudou" in html
    assert html.index("Backend Python Pleno") < html.index("Desenvolvedor Python")


def test_manual_queue_is_default_sorted_and_explains_why(client, seeded):
    html = client.get("/fila").text
    titles = ["Python Gupy", "Desenvolvedor Python", "Engenheiro de Software"]
    positions = [html.index(t) for t in titles]
    assert positions == sorted(positions)
    assert "Backend Python Pleno" not in html, "nota 91 sem alerta no Greenhouse é automática"
    assert "Ainda sem nota" not in html, "vaga sem nota do LLM não entra na fila"
    assert "exige inglês fluente" in html
    assert "gupy: candidatura só manual" in html
    assert "nota abaixo de 85" in html
    assert "Manual (3)" in html and "Automática (1)" in html

    filtered = client.get("/fila?view=manual&min=60").text
    assert "Python Gupy" in filtered
    assert "Engenheiro de Software" not in filtered


def test_auto_queue(client, seeded):
    html = client.get("/fila?view=auto").text
    assert "Backend Python Pleno" in html
    assert "Fila automática" in html
    assert "Python Gupy" not in html


def test_threshold_moves_jobs_between_queues(sessions, seeded):
    html = TestClient(create_app(sessions, auto_threshold=95)).get("/fila?view=auto").text
    assert "Backend Python Pleno" not in html
    assert "Nada na fila automática" in html


def test_done_moves_job_out_of_queue_and_updates_count(client, sessions, seeded):
    resp = client.post(f"/jobs/{seeded['top']}/done", headers=HX)

    assert resp.status_code == 200
    assert "Aplicada" in resp.text and "Desfazer" in resp.text
    assert 'id="queue-count"' in resp.text and ">3<" in resp.text, "contador da fila via OOB"
    assert "Backend Python Pleno" not in client.get("/fila?view=auto").text
    assert "Backend Python Pleno" in client.get("/fila?view=aplicadas").text

    with sessions() as s:
        app = s.scalars(select(Application)).one()
        assert app.status is ApplicationStatus.APPLIED_MANUAL
        assert app.risk is RiskLevel.LOW
        assert app.applied_at is not None


def test_discard_then_undo_returns_to_queue(client, sessions, seeded):
    client.post(f"/jobs/{seeded['gupy']}/discard", headers=HX)
    assert "Python Gupy" in client.get("/fila?view=descartadas").text

    resp = client.post(f"/jobs/{seeded['gupy']}/undo", headers=HX)
    assert "Done" in resp.text, "volta como card completo"
    assert "Python Gupy" in client.get("/fila").text
    with sessions() as s:
        app = s.scalars(select(Application)).one()
        assert app.status is ApplicationStatus.QUEUED
        assert app.risk is RiskLevel.MEDIUM


def test_decide_is_idempotent(client, sessions, seeded):
    for _ in range(2):
        client.post(f"/jobs/{seeded['mid']}/done", headers=HX)
    with sessions() as s:
        assert len(s.scalars(select(Application)).all()) == 1


def test_post_without_htmx_header_is_rejected(client, seeded):
    assert client.post(f"/jobs/{seeded['top']}/done").status_code == 403


def test_unknown_job_is_404(client):
    assert client.post("/jobs/999/done", headers=HX).status_code == 404


def test_mercado_shows_median_by_level_and_contract(client, seeded):
    html = client.get("/mercado").text
    assert "pleno" in html and "CLT" in html
    assert "R$ 7.000" in html, "mediana de 6.000 e 8.000"


def test_static_and_health(client):
    assert client.get("/static/style.css").status_code == 200
    assert client.get("/healthz").json()["ok"] is True
