"""Painel local: relatório da noite, fila de revisão e mercado (docs/ESCOPO.md §8)."""

import json
from collections.abc import Callable, Iterator
from datetime import UTC, datetime
from pathlib import Path
from typing import Annotated
from urllib.parse import urlencode

from fastapi import Depends, FastAPI, Form, HTTPException, Query, Request
from fastapi.responses import FileResponse, HTMLResponse, Response
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from sqlalchemy.exc import NoResultFound
from sqlalchemy.orm import Session, sessionmaker

from night_shift import __version__
from night_shift.adapters.storage.funnel import REJECTED as FUNNEL_REJECTED
from night_shift.adapters.storage.funnel import STAGES as FUNNEL_STAGES
from night_shift.adapters.storage.funnel import FunnelRepository
from night_shift.adapters.storage.models import Job
from night_shift.adapters.storage.outreach import OutreachRepository
from night_shift.adapters.storage.review import ORDERS, ReviewRepository
from night_shift.application.outreach import linkedin_people_search
from night_shift.domain.enums import ApplicationStatus, OutreachStatus
from night_shift.domain.lanes import Lane, manual_reason
from night_shift.web.live import live_context

HERE = Path(__file__).parent
templates = Jinja2Templates(directory=HERE / "templates")

# Abas da Fila: filas de pendentes (por lane) e decididas (por status).
# Atualizações (a cada 2 s) esperando a tarefa disparada criar a execução nova.
WAIT_POLLS = 20
# Hoje: notas dos últimos N dias contam como novas; candidatura sem resposta há N dias
# aparece para cobrar (o Teal sugere 1 e 2 semanas).
FRESH_DAYS = 7
FOLLOW_UP_DAYS = 7

LANE_VIEWS = {"manual": Lane.MANUAL, "auto": Lane.AUTO}
STATUS_VIEWS = {
    "aplicadas": (ApplicationStatus.APPLIED_MANUAL, ApplicationStatus.AUTO_APPLIED),
    "descartadas": (ApplicationStatus.DISCARDED,),
}


# ------------------------------------------------------------------ filtros


def brl(value: int | None) -> str:
    return "—" if value is None else "R$ " + f"{value:,}".replace(",", ".")


def local_dt(value: datetime | None) -> str:
    """O SQLite devolve datetime sem fuso; gravamos sempre em UTC."""
    if value is None:
        return "—"
    if value.tzinfo is None:
        value = value.replace(tzinfo=UTC)
    return value.astimezone().strftime("%d/%m %H:%M")


def duration(start: datetime, end: datetime | None) -> str:
    if end is None:
        return "em andamento"
    secs = int((end - start).total_seconds())
    return f"{secs // 60}min {secs % 60:02d}s" if secs >= 60 else f"{secs}s"


def score_class(score: int | None) -> str:
    if score is None:
        return "none"
    return "high" if score >= 75 else "mid" if score >= 50 else "low"


templates.env.filters.update(brl=brl, local_dt=local_dt, score_class=score_class)


def toast(response: Response, message: str, undo: str | None = None, card: str | None = None):
    """Aviso rápido no canto da tela (evento ``toast`` do htmx, tratado em app.js); com
    ``undo``, o aviso traz um botão Desfazer que aciona o desfazer do cartão ``card``.

    O campo não pode se chamar ``target``: no HX-Trigger, o htmx usa ``target`` para
    escolher onde disparar o evento, e ``null`` ali quebra a resposta."""
    payload = {"message": message, "undo": undo, "card": card}
    response.headers["HX-Trigger"] = json.dumps({"toast": payload})  # ASCII: cabe no header
    return response


def gmail_compose(to: str, subject: str, body: str) -> str:
    """Abre o Gmail na web com o e-mail pronto (você anexa o CV e envia)."""
    query = urlencode({"view": "cm", "fs": "1", "to": to, "su": subject, "body": body})
    return f"https://mail.google.com/mail/?{query}"


STATUS_LABELS = {
    "queued": "na fila",
    "applied_manual": "aplicada",
    "auto_applied": "aplicada (night-shift)",
    "replied": "resposta",
    "interview": "entrevista",
    "offer": "proposta",
    "rejected": "recusada",
    "discarded": "descartada",
}


def status_label(status) -> str:
    return STATUS_LABELS.get(str(status), str(status))


# Muda sempre que um arquivo estático muda: o navegador baixa o novo em vez do cache.
ASSET_VERSION = str(int(max(f.stat().st_mtime for f in (HERE / "static").iterdir())))

templates.env.globals.update(
    asset_version=ASSET_VERSION,
    status_label=status_label,
    duration=duration,
    version=__version__,
    gmail_compose=gmail_compose,
    linkedin_search=linkedin_people_search,
)


# ---------------------------------------------------------------------- app


def create_app(
    sessions: sessionmaker[Session],
    auto_threshold: int = 85,
    cv_dir: Path | None = None,
    shots_dir: Path | None = None,
    schedule_status: Callable[[], str] | None = None,
    on_turn_off: Callable[[], list[str]] | None = None,
    logs_dir: Path | None = None,
    request_stop: Callable[[], None] | None = None,
    start_run: Callable[[], str] | None = None,
    outreach_daily_limit: int = 10,
) -> FastAPI:
    """``auto_threshold``: nota mínima para uma vaga de fonte de baixo risco ir para a fila
    automática (``automation.auto_apply_min_score`` no profile.yaml)."""
    app = FastAPI(title="night-shift", docs_url=None, redoc_url=None)
    app.mount("/static", StaticFiles(directory=HERE / "static"), name="static")

    def repo() -> Iterator[ReviewRepository]:
        with sessions.begin() as s:
            yield ReviewRepository(s, auto_threshold)

    Repo = Annotated[ReviewRepository, Depends(repo)]

    def card_ctx(repo: ReviewRepository) -> dict:
        def reason_of(sc):
            return manual_reason(sc.job.source, sc.llm_score, sc.red_flags or [], auto_threshold)

        return {"lane_of": repo.lane, "reason_of": reason_of, "auto_threshold": auto_threshold}

    def page(request: Request, name: str, repo: ReviewRepository, **ctx) -> HTMLResponse:
        ctx.setdefault("counts", repo.counts())
        orepo = OutreachRepository(repo.s)
        ctx.setdefault("ocounts", orepo.counts())
        ctx.setdefault("ready_emails", orepo.drafts_with_email())
        ctx.update(card_ctx(repo))
        ctx.setdefault("can_start", start_run is not None)
        ctx.setdefault("can_turn_off", on_turn_off is not None)
        return templates.TemplateResponse(request, name, ctx)

    @app.get("/", response_class=HTMLResponse)
    def hoje(request: Request, repo: Repo):
        runs = repo.recent_runs(6)
        last = runs[0] if runs else None
        fresh = repo.fresh_best(days=FRESH_DAYS)
        return page(
            request,
            "hoje.html",
            repo,
            active="hoje",
            last=last,
            older=runs[1:],
            fresh=fresh,
            # Sem nota nova na semana, mostra as melhores que ainda estão na fila.
            best=fresh or repo.queue(limit=5),
            emails_ready=OutreachRepository(repo.s).drafts_with_email(),
            waiting=repo.awaiting_reply(days=FOLLOW_UP_DAYS),
            fresh_days=FRESH_DAYS,
            follow_up_days=FOLLOW_UP_DAYS,
            schedule=schedule_status() if schedule_status else None,
            can_turn_off=on_turn_off is not None,
        )

    @app.get("/fila", response_class=HTMLResponse)
    def fila(
        request: Request,
        repo: Repo,
        view: Annotated[str, Query(pattern="^(manual|auto|aplicadas|descartadas)$")] = "manual",
        min_score: Annotated[int, Query(alias="min", ge=0, le=100)] = 0,
        stack: Annotated[str, Query(pattern="^(|python|ia|java)$")] = "",
        q: Annotated[str, Query(max_length=100)] = "",
        ordem: Annotated[str, Query(pattern="^(nota|recentes|empresa)$")] = "nota",
    ):
        if view in LANE_VIEWS:
            scores = repo.queue(
                LANE_VIEWS[view], min_score, stack=stack or None, search=q, order=ordem
            )
        else:
            scores = repo.decided(STATUS_VIEWS[view])
        return page(
            request,
            "fila.html",
            repo,
            active="fila",
            view=view,
            min_score=min_score,
            stack=stack,
            q=q,
            ordem=ordem,
            orders=ORDERS,
            scores=scores,
        )

    def _decide(request: Request, repo: ReviewRepository, job_id: int, status):
        # Só o HTMX do próprio painel manda esse header; um <form> de outro site não consegue
        # (exigiria preflight CORS), então isso basta como proteção CSRF num app local.
        if request.headers.get("HX-Request") != "true":
            raise HTTPException(403, "use o painel")
        try:
            score = repo.decide(job_id, status) if status else repo.undo(job_id)
        except NoResultFound as e:
            raise HTTPException(404, "vaga não encontrada") from e
        template = "_card.html" if status is None else "_decided.html"
        ctx = {"sc": score, "counts": repo.counts(), "oob": True, **card_ctx(repo)}
        response = templates.TemplateResponse(request, template, ctx)
        title = f"{score.job.title} · {score.job.company_name}"
        if status is None:
            return toast(response, f"De volta na fila: {title}")
        verb = (
            "Marcada como aplicada" if status is ApplicationStatus.APPLIED_MANUAL else "Descartada"
        )
        return toast(response, f"{verb}: {title}", f"/jobs/{job_id}/undo", f"#job-{job_id}")

    @app.post("/jobs/{job_id}/done", response_class=HTMLResponse)
    def done(request: Request, repo: Repo, job_id: int):
        return _decide(request, repo, job_id, ApplicationStatus.APPLIED_MANUAL)

    @app.post("/jobs/{job_id}/discard", response_class=HTMLResponse)
    def discard(request: Request, repo: Repo, job_id: int):
        return _decide(request, repo, job_id, ApplicationStatus.DISCARDED)

    @app.post("/jobs/{job_id}/undo", response_class=HTMLResponse)
    def undo(request: Request, repo: Repo, job_id: int):
        return _decide(request, repo, job_id, None)

    # --------------------------------------------------------------- outreach

    # (status, com e-mail?) de cada aba; "pendentes" é o nome antigo de "com-email".
    OUTREACH_VIEWS = {
        "com-email": ((OutreachStatus.DRAFT,), True),
        "sem-email": ((OutreachStatus.DRAFT,), False),
        "enviadas": ((OutreachStatus.SENT, OutreachStatus.REPLIED), None),
        "descartadas": ((OutreachStatus.DISCARDED,), None),
    }

    def outreach_cv() -> str | None:
        """O CV Python em português (código 11), o que vai anexo no e-mail de outreach."""
        if cv_dir is None:
            return None
        found = sorted(cv_dir.glob("cv_*_11[0-9][0-9][0-9].pdf"))
        return found[0].name if found else None

    @app.get("/outreach", response_class=HTMLResponse)
    def outreach_page(
        request: Request,
        repo: Repo,
        view: Annotated[
            str, Query(pattern="^(|pendentes|com-email|sem-email|enviadas|descartadas)$")
        ] = "",
    ):
        orepo = OutreachRepository(repo.s)
        with_email = orepo.drafts_with_email()
        if view in ("", "pendentes"):
            # Abre no que dá para enviar agora; sem nenhum e-mail pronto, nos de LinkedIn.
            view = "com-email" if with_email or not orepo.counts().get("draft") else "sem-email"
        statuses, has_email = OUTREACH_VIEWS[view]
        return page(
            request,
            "outreach.html",
            repo,
            active="outreach",
            view=view,
            items=orepo.by_status(*statuses, with_email=has_email),
            with_email=with_email,
            outreach_cv=outreach_cv(),
            daily_limit=outreach_daily_limit,
        )

    OUTREACH_ACTIONS = {
        "sent": OutreachStatus.SENT,
        "discard": OutreachStatus.DISCARDED,
        "replied": OutreachStatus.REPLIED,
        "undo": OutreachStatus.DRAFT,
    }

    @app.post("/outreach/{outreach_id}/{action}", response_class=HTMLResponse)
    def outreach_action(request: Request, repo: Repo, outreach_id: int, action: str):
        if request.headers.get("HX-Request") != "true":
            raise HTTPException(403, "use o painel")
        if action not in OUTREACH_ACTIONS:
            raise HTTPException(404)
        try:
            row = OutreachRepository(repo.s).set_status(outreach_id, OUTREACH_ACTIONS[action])
        except NoResultFound as e:
            raise HTTPException(404, "mensagem não encontrada") from e
        ctx = {"o": row, "counts": repo.counts(), "oob": True, **card_ctx(repo)}
        response = templates.TemplateResponse(request, "_outreach_card.html", ctx)
        name = row.company.name
        messages = {
            "sent": f"Marcada como enviada: {name}",
            "discard": f"Descartada: {name}",
            "replied": f"Responderam: {name}",
            "undo": f"De volta para enviar: {name}",
        }
        undo = None if action == "undo" else f"/outreach/{outreach_id}/undo"
        return toast(response, messages[action], undo, f"#outreach-{outreach_id}")

    # ------------------------------------------------------------------ funil

    def board_ctx(repo: ReviewRepository) -> dict:
        frepo = FunnelRepository(repo.s)
        board = frepo.board()
        sent, replied = frepo.outreach_stats()
        job_ids = [app.job_id for apps in board.values() for app in apps]
        return {
            "board": board,
            "stages": FUNNEL_STAGES,
            "all_stages": [*FUNNEL_STAGES, FUNNEL_REJECTED],
            "conversions": frepo.conversions(),
            "notes": frepo.notes(job_ids),
            "outreach_sent": sent,
            "outreach_replied": replied,
        }

    @app.get("/funil", response_class=HTMLResponse)
    def funil(request: Request, repo: Repo):
        return page(request, "funil.html", repo, active="funil", **board_ctx(repo))

    @app.post("/funil/{job_id}/mover/{to}", response_class=HTMLResponse)
    def funil_mover(request: Request, repo: Repo, job_id: int, to: str):
        if request.headers.get("HX-Request") != "true":
            raise HTTPException(403, "use o painel")
        try:
            app_row = FunnelRepository(repo.s).move(job_id, to)
        except (KeyError, NoResultFound) as e:
            raise HTTPException(404, "candidatura ou etapa não encontrada") from e
        response = templates.TemplateResponse(request, "_board.html", board_ctx(repo))
        stage = status_label(app_row.status)
        return toast(response, f"{app_row.job.title}: {stage}")

    @app.post("/jobs/{job_id}/notas", response_class=HTMLResponse)
    def anotar(request: Request, repo: Repo, job_id: int, texto: Annotated[str, Form()]):
        if request.headers.get("HX-Request") != "true":
            raise HTTPException(403, "use o painel")
        if not texto.strip() or len(texto) > 2000:
            raise HTTPException(422, "anotação vazia ou longa demais")
        try:
            FunnelRepository(repo.s).add_note(job_id, texto)
        except NoResultFound as e:
            raise HTTPException(404, "vaga não encontrada") from e
        return templates.TemplateResponse(request, "_board.html", board_ctx(repo))

    @app.get("/mercado", response_class=HTMLResponse)
    def mercado(request: Request, repo: Repo):
        return page(
            request,
            "mercado.html",
            repo,
            active="mercado",
            buckets=repo.salary_buckets(),
            jobs=repo.jobs_with_salary(),
        )

    @app.get("/jobs/{job_id}/cv")
    def cv_pdf(job_id: int):
        with sessions() as s:
            job = s.get(Job, job_id)
            path = job.application.cv_variant_path if job and job.application else None
        if not path:
            raise HTTPException(404, "esta vaga não tem CV ajustado")
        pdf = Path(path).resolve()
        # Só serve arquivo de dentro da pasta de CVs, mesmo que o banco tenha outro caminho.
        if cv_dir is None or not pdf.is_relative_to(cv_dir.resolve()) or not pdf.exists():
            raise HTTPException(404, "arquivo do CV não encontrado")
        return FileResponse(pdf, media_type="application/pdf", filename=pdf.name)

    @app.get("/jobs/{job_id}/shot/{kind}")
    def apply_shot(job_id: int, kind: str):
        key = {"preenchido": "filled_shot", "confirmado": "confirmed_shot"}.get(kind)
        with sessions() as s:
            job = s.get(Job, job_id)
            apply = ((job.application.answers or {}) if job and job.application else {}).get(
                "apply"
            ) or {}
        path = apply.get(key) if key else None
        if not path:
            raise HTTPException(404, "sem print")
        png = Path(path).resolve()
        if shots_dir is None or not png.is_relative_to(shots_dir.resolve()) or not png.exists():
            raise HTTPException(404, "arquivo do print não encontrado")
        return FileResponse(png, media_type="image/png")

    @app.post("/system/off", response_class=HTMLResponse)
    def system_off(request: Request):
        if request.headers.get("HX-Request") != "true":
            raise HTTPException(403, "use o painel")
        if on_turn_off is None:
            raise HTTPException(404)
        lines = on_turn_off()
        return templates.TemplateResponse(request, "_turned_off.html", {"lines": lines})

    # ---------------------------------------------------------------- ao vivo

    def live(request: Request, repo: ReviewRepository, message: str | None = None):
        ctx = live_context(repo, logs_dir)
        ctx.update(
            card_ctx(repo),
            message=message,
            can_stop=request_stop is not None,
            can_start=start_run is not None,
        )
        return ctx

    @app.get("/ao-vivo", response_class=HTMLResponse)
    def ao_vivo(request: Request, repo: Repo, msg: str | None = None):
        ctx = live(request, repo, msg)
        if msg and not ctx["running"]:
            # Acabou de vir do botão "Buscar vagas": espera a execução nova aparecer.
            ctx.update(waiting=WAIT_POLLS, waiting_since=ctx["run"].id if ctx["run"] else 0)
        return page(request, "ao_vivo.html", repo, active="ao-vivo", **ctx)

    @app.post("/buscar")
    def buscar(request: Request):
        """Botão "Buscar vagas" do topo: dispara a busca e leva para a página Ao vivo."""
        if request.headers.get("HX-Request") != "true":
            raise HTTPException(403, "use o painel")
        if start_run is None:
            raise HTTPException(404)
        msg = start_run()
        return Response(
            status_code=204, headers={"HX-Redirect": f"/ao-vivo?{urlencode({'msg': msg})}"}
        )

    @app.get("/ao-vivo/estado", response_class=HTMLResponse)
    def ao_vivo_estado(
        request: Request,
        repo: Repo,
        esperando: Annotated[int, Query(ge=0, le=WAIT_POLLS)] = 0,
        desde: Annotated[int, Query(ge=0)] = 0,
    ):
        ctx = live(request, repo)
        # Depois do "Rodar agora", a tarefa leva alguns segundos para criar o Run novo:
        # enquanto o último Run for o de antes (id <= desde), continua esperando.
        if esperando and (ctx["run"] is None or ctx["run"].id <= desde):
            ctx.update(waiting=esperando - 1, waiting_since=desde)
        return templates.TemplateResponse(request, "_live.html", ctx)

    @app.post("/ao-vivo/parar", response_class=HTMLResponse)
    def ao_vivo_parar(request: Request, repo: Repo):
        if request.headers.get("HX-Request") != "true":
            raise HTTPException(403, "use o painel")
        if request_stop is None:
            raise HTTPException(404)
        request_stop()
        msg = "Parada pedida: termina a vaga atual e encerra."
        return templates.TemplateResponse(request, "_live.html", live(request, repo, msg))

    @app.post("/ao-vivo/iniciar", response_class=HTMLResponse)
    def ao_vivo_iniciar(request: Request, repo: Repo):
        if request.headers.get("HX-Request") != "true":
            raise HTTPException(403, "use o painel")
        if start_run is None:
            raise HTTPException(404)
        msg = start_run()
        ctx = live(request, repo, msg)
        if ctx["run"] is None or not ctx["running"]:
            ctx.update(waiting=WAIT_POLLS, waiting_since=ctx["run"].id if ctx["run"] else 0)
        return templates.TemplateResponse(request, "_live.html", ctx)

    @app.get("/healthz")
    def healthz():
        return {"ok": True, "version": __version__}

    return app
