"""Painel local: relatório da noite, fila de revisão e mercado (docs/ESCOPO.md §8)."""

from collections.abc import Iterator
from datetime import UTC, datetime
from pathlib import Path
from typing import Annotated

from fastapi import Depends, FastAPI, HTTPException, Query, Request
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from sqlalchemy.exc import NoResultFound
from sqlalchemy.orm import Session, sessionmaker

from night_shift import __version__
from night_shift.adapters.storage.review import ReviewRepository
from night_shift.domain.enums import ApplicationStatus

HERE = Path(__file__).parent
templates = Jinja2Templates(directory=HERE / "templates")

STATUS_VIEWS = {
    "fila": None,
    "aplicadas": ApplicationStatus.APPLIED_MANUAL,
    "descartadas": ApplicationStatus.DISCARDED,
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
templates.env.globals.update(duration=duration, version=__version__)


# ---------------------------------------------------------------------- app


def create_app(sessions: sessionmaker[Session]) -> FastAPI:
    app = FastAPI(title="night-shift", docs_url=None, redoc_url=None)
    app.mount("/static", StaticFiles(directory=HERE / "static"), name="static")

    def repo() -> Iterator[ReviewRepository]:
        with sessions.begin() as s:
            yield ReviewRepository(s)

    Repo = Annotated[ReviewRepository, Depends(repo)]

    def page(request: Request, name: str, repo: ReviewRepository, **ctx) -> HTMLResponse:
        ctx.setdefault("counts", repo.counts())
        return templates.TemplateResponse(request, name, ctx)

    @app.get("/", response_class=HTMLResponse)
    def hoje(request: Request, repo: Repo):
        runs = repo.recent_runs(6)
        last = runs[0] if runs else None
        return page(
            request,
            "hoje.html",
            repo,
            active="hoje",
            last=last,
            older=runs[1:],
            best=repo.best_of_run(last) if last else [],
        )

    @app.get("/fila", response_class=HTMLResponse)
    def fila(
        request: Request,
        repo: Repo,
        view: Annotated[str, Query(pattern="^(fila|aplicadas|descartadas)$")] = "fila",
        min_score: Annotated[int, Query(alias="min", ge=0, le=100)] = 0,
    ):
        status = STATUS_VIEWS[view]
        scores = repo.queue(min_score) if status is None else repo.decided(status)
        return page(
            request,
            "fila.html",
            repo,
            active="fila",
            view=view,
            min_score=min_score,
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
        ctx = {"sc": score, "counts": repo.counts(), "oob": True}
        return templates.TemplateResponse(request, template, ctx)

    @app.post("/jobs/{job_id}/done", response_class=HTMLResponse)
    def done(request: Request, repo: Repo, job_id: int):
        return _decide(request, repo, job_id, ApplicationStatus.APPLIED_MANUAL)

    @app.post("/jobs/{job_id}/discard", response_class=HTMLResponse)
    def discard(request: Request, repo: Repo, job_id: int):
        return _decide(request, repo, job_id, ApplicationStatus.DISCARDED)

    @app.post("/jobs/{job_id}/undo", response_class=HTMLResponse)
    def undo(request: Request, repo: Repo, job_id: int):
        return _decide(request, repo, job_id, None)

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

    @app.get("/healthz")
    def healthz():
        return {"ok": True, "version": __version__}

    return app
