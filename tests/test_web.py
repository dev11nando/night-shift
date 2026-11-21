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


def test_card_shows_letter_and_serves_cv_only_from_cv_dir(sessions, seeded, tmp_path):
    cv_dir = tmp_path / "output" / "cv"
    cv_dir.mkdir(parents=True)
    pdf = cv_dir / "1-fintech-x.pdf"
    pdf.write_bytes(b"%PDF-1.4 teste")
    outside = tmp_path / "segredo.pdf"
    outside.write_bytes(b"%PDF-1.4 fora")
    with sessions.begin() as s:
        s.add(
            Application(
                job_id=seeded["top"],
                risk=RiskLevel.LOW,
                cv_variant_path=str(pdf),
                cover_letter="Olá, time.\n\nMarcos",
                answers={"letter_subject": "Candidatura: Backend"},
            )
        )
        s.add(Application(job_id=seeded["mid"], risk=RiskLevel.LOW, cv_variant_path=str(outside)))

    client = TestClient(create_app(sessions, cv_dir=cv_dir))
    html = client.get("/fila?view=auto").text
    assert "Carta de apresentação" in html and "Assunto: Candidatura: Backend" in html
    assert f'href="/jobs/{seeded["top"]}/cv"' in html

    resp = client.get(f"/jobs/{seeded['top']}/cv")
    assert resp.status_code == 200 and resp.content.startswith(b"%PDF")
    assert client.get(f"/jobs/{seeded['mid']}/cv").status_code == 404, "fora da pasta de CVs"
    assert client.get(f"/jobs/{seeded['low']}/cv").status_code == 404, "sem CV"


def test_hoje_shows_schedule_and_turn_off_button(sessions, seeded):
    calls = []
    client = TestClient(
        create_app(
            sessions,
            schedule_status=lambda: "todo dia às 02:00",
            on_turn_off=lambda: calls.append(1) or ["tarefa agendada desligada"],
        )
    )
    html = client.get("/").text
    assert "Agendamento: todo dia às 02:00" in html
    assert 'hx-post="/system/off"' in html

    assert client.post("/system/off").status_code == 403
    resp = client.post("/system/off", headers=HX)
    assert "night-shift desligado" in resp.text and "tarefa agendada desligada" in resp.text
    assert calls == [1]


def test_turn_off_button_hidden_without_handler(client, seeded):
    assert "/system/off" not in client.get("/").text
    assert client.post("/system/off", headers=HX).status_code == 404


def test_assisted_apply_shows_in_applied_tab_with_screenshots(sessions, seeded, tmp_path):
    shots = tmp_path / "output" / "applications"
    shots.mkdir(parents=True)
    filled = shots / "1-preenchido.png"
    filled.write_bytes(b"\x89PNG fake")
    with sessions.begin() as s:
        s.add(
            Application(
                job_id=seeded["top"],
                risk=RiskLevel.LOW,
                status=ApplicationStatus.AUTO_APPLIED,
                answers={
                    "apply": {
                        "status": "applied",
                        "filled": ["Nome*", "E-mail*"],
                        "resume_attached": True,
                        "unanswered_required": [],
                        "captcha": "recaptcha",
                        "filled_shot": str(filled),
                        "confirmed_shot": str(tmp_path / "fora.png"),
                    }
                },
            )
        )
    client = TestClient(create_app(sessions, shots_dir=shots))

    html = client.get("/fila?view=aplicadas").text
    assert "Aplicada com o night-shift" in html and "2 campo(s) preenchido(s)" in html
    assert "Aplicadas (1)" in html
    assert client.get(f"/jobs/{seeded['top']}/shot/preenchido").status_code == 200
    assert client.get(f"/jobs/{seeded['top']}/shot/confirmado").status_code == 404, "fora da pasta"
    assert client.get(f"/jobs/{seeded['top']}/shot/qualquer").status_code == 404


# -------------------------------------------------------------------- ao vivo


def test_live_page_without_runs(client):
    html = client.get("/ao-vivo").text
    assert "Nenhuma execução ainda" in html and "every 2s" not in html


def test_live_page_while_running_polls_and_shows_progress(sessions, seeded, tmp_path):
    from datetime import timedelta

    logs = tmp_path / "logs"
    logs.mkdir()
    log = logs / "20261122-020000-run.log"
    log.write_text("02:00:01 coleta\n02:03:00 nota do LLM\n", encoding="utf-8")
    with sessions.begin() as s:
        s.add(
            Run(
                stats={"collected": 900, "llm_scored": 4},
                errors=[],
                stage="nota",
                current_item="[5/30] Backend Python — Stone",
                budget_ends_at=utcnow() + timedelta(minutes=90),
                log_path=str(log),
            )
        )
    stops, starts = [], []
    client = TestClient(
        create_app(
            sessions,
            logs_dir=logs,
            request_stop=lambda: stops.append(1),
            start_run=lambda: starts.append(1) or "Rodada iniciada",
        )
    )

    html = client.get("/ao-vivo/estado").text
    assert 'hx-trigger="every 2s"' in html
    assert '<li class="active">Nota do LLM</li>' in html
    assert '<li class="done">Coleta</li>' in html
    assert "[5/30] Backend Python — Stone" in html
    assert "<b>900</b>" in html
    assert "1h29min" in html or "1h30min" in html
    assert "nota do LLM" in html, "fim do log"

    assert client.post("/ao-vivo/parar").status_code == 403
    assert "Parada pedida" in client.post("/ao-vivo/parar", headers=HX).text
    assert stops == [1]


def test_live_page_after_finish_stops_polling_and_can_start(sessions, tmp_path):
    with sessions.begin() as s:
        s.add(
            Run(
                stats={"collected": 10},
                errors=["gupy: fora do ar"],
                stage="documentos",
                status=RunStatus.SUCCESS,
                finished_at=utcnow(),
                log_path=str(tmp_path / "fora-de-logs.log"),
            )
        )
    (tmp_path / "fora-de-logs.log").write_text("segredo", encoding="utf-8")
    client = TestClient(
        create_app(sessions, logs_dir=tmp_path / "logs", start_run=lambda: "Rodada iniciada")
    )
    html = client.get("/ao-vivo").text
    assert "every 2s" not in html.split('id="live"')[1].split(">")[0]
    assert "concluída" in html and "gupy: fora do ar" in html
    assert "segredo" not in html, "log fora da pasta de logs não é lido"

    started = client.post("/ao-vivo/iniciar", headers=HX).text
    assert "Rodada iniciada" in started and 'hx-trigger="every 2s"' in started


def test_start_keeps_polling_until_the_new_run_appears(sessions):
    with sessions.begin() as s:
        s.add(Run(stats={}, errors=[], status=RunStatus.SUCCESS, finished_at=utcnow()))
    client = TestClient(create_app(sessions, start_run=lambda: "Rodada iniciada"))

    started = client.post("/ao-vivo/iniciar", headers=HX).text
    assert "esperando=20&amp;desde=1" in started or "esperando=20&desde=1" in started

    # A tarefa ainda não criou o Run novo: continua esperando, com uma tentativa a menos.
    waiting = client.get("/ao-vivo/estado?esperando=20&desde=1").text
    assert "esperando=19" in waiting and "Disparando a rodada" in waiting

    with sessions.begin() as s:
        s.add(Run(stats={"collected": 1}, errors=[]))  # a tarefa começou
    live = client.get("/ao-vivo/estado?esperando=19&desde=1").text
    assert "esperando" not in live and 'hx-get="/ao-vivo/estado"' in live

    gave_up = client.get("/ao-vivo/estado?esperando=0&desde=99").text
    assert "every 2s" in live and "Disparando" not in gave_up


def test_header_buttons_and_buscar_redirects_to_live(sessions):
    started = []
    client = TestClient(
        create_app(
            sessions,
            start_run=lambda: started.append(1) or "Busca iniciada",
            on_turn_off=lambda: ["ok"],
        )
    )
    for path in ("/", "/fila", "/mercado", "/ao-vivo"):
        html = client.get(path).text
        assert 'hx-post="/buscar"' in html and ">Desligar</button>" in html, path

    assert client.post("/buscar").status_code == 403
    resp = client.post("/buscar", headers=HX)
    assert resp.status_code == 204 and started == [1]
    assert resp.headers["HX-Redirect"].startswith("/ao-vivo?msg=Busca")

    page = client.get(resp.headers["HX-Redirect"]).text
    assert "Busca iniciada" in page and "esperando=20" in page


def test_header_buttons_hidden_without_handlers(client):
    html = client.get("/").text
    assert "/buscar" not in html and ">Desligar</button>" not in html
