import json
import sys
import urllib.error
import urllib.request

import typer

from night_shift import __version__
from night_shift.adapters.llm.ollama import OllamaEmbedder, OllamaLLM
from night_shift.adapters.sources import build_sources
from night_shift.adapters.sources.ats import ATS_SOURCES
from night_shift.adapters.sources.http import PoliteClient, make_client
from night_shift.adapters.storage import db
from night_shift.adapters.storage.repository import JobRepository
from night_shift.application.pipeline import Pipeline
from night_shift.config import (
    CompanyConfig,
    ConfigError,
    LLMConfig,
    Profile,
    bootstrap_config,
    load_companies,
    load_cv,
    load_profile,
)
from night_shift.domain.enums import RunStatus
from night_shift.domain.filters import HardFilter
from night_shift.paths import ProjectPaths
from night_shift.ports import SourceError
from night_shift.runtime.job_object import IS_WINDOWS, is_store_python
from night_shift.runtime.lifecycle import enter_managed_process
from night_shift.runtime.stop_flag import StopFlag

app = typer.Typer(
    help="night-shift: busca, avalia e se candidata a vagas enquanto você dorme.",
    no_args_is_help=True,
)
db_app = typer.Typer(help="Banco de dados (SQLite + Alembic).", no_args_is_help=True)
app.add_typer(db_app, name="db")
companies_app = typer.Typer(help="Empresas-alvo.", no_args_is_help=True)
app.add_typer(companies_app, name="companies")


@app.callback()
def _main() -> None:
    # Saída redirecionada (Agendador de Tarefas, pipe) usa cp1252 no Windows: um caractere
    # fora dela não pode derrubar o comando.
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(errors="replace")


def _paths() -> ProjectPaths:
    return ProjectPaths.from_env()


@app.command()
def version() -> None:
    """Mostra a versão."""
    typer.echo(__version__)


@app.command()
def init() -> None:
    """Cria pastas, copia os *.example.yaml que faltam e aplica as migrations."""
    paths = _paths()
    paths.ensure_dirs()
    for created in bootstrap_config(paths.config_dir):
        typer.echo(f"criado: {created.relative_to(paths.root)}  -> preencha com seus dados")
    db.upgrade(paths.db_url)
    typer.echo(f"banco pronto: {paths.db_path.relative_to(paths.root)}")


@db_app.command("upgrade")
def db_upgrade(revision: str = typer.Argument("head")) -> None:
    """Aplica migrations até a revisão indicada."""
    paths = _paths()
    paths.ensure_dirs()
    db.upgrade(paths.db_url, revision)
    typer.echo(f"ok: {revision}")


@app.command()
def doctor() -> None:
    """Checa config, banco, Ollama e suporte a Job Object."""
    paths = _paths()
    ok = True

    def report(good: bool, label: str, detail: str = "") -> None:
        nonlocal ok
        ok &= good
        mark = typer.style("ok  ", fg="green") if good else typer.style("FAIL", fg="red")
        typer.echo(f"[{mark}] {label}" + (f": {detail}" if detail else ""))

    typer.echo(f"raiz: {paths.root}")

    profile = None
    try:
        profile = load_profile(paths.profile_file)
        report(
            True,
            "config/profile.yaml",
            f"automação {'ON' if profile.automation.enabled else 'OFF'}",
        )
    except ConfigError as e:
        report(False, "config/profile.yaml", str(e))

    if paths.db_path.exists():
        engine = db.make_engine(paths.db_url)
        try:
            current = db.current_revision(engine)
        finally:
            engine.dispose()
        head = db.head_revision()
        report(current == head, "banco", f"revisão {current} (head {head})")
    else:
        report(False, "banco", "não existe, rode `night-shift init`")

    # Ollama só é exigido pelo `rank`; a coleta funciona sem ele, então aqui é só aviso.
    def warn(label: str, detail: str) -> None:
        typer.echo(f"[{typer.style('warn', fg='yellow')}] {label}: {detail}")

    llm = profile.llm if profile else LLMConfig()
    try:
        with urllib.request.urlopen(f"{llm.ollama_url}/api/tags", timeout=2) as resp:
            models = [m["name"] for m in json.load(resp).get("models", [])]
    except (urllib.error.URLError, OSError, ValueError):
        warn("ollama", f"não encontrado em {llm.ollama_url} (necessário para `rank`)")
    else:
        names = {m.removesuffix(":latest") for m in models}
        missing = [m for m in (llm.local_model, llm.embed_model) if m not in names]
        if missing:
            warn("ollama", "faltam modelos: " + ", ".join(f"`ollama pull {m}`" for m in missing))
        else:
            report(True, "ollama", f"{llm.local_model} + {llm.embed_model}")

    if IS_WINDOWS:
        try:
            import win32job  # noqa: F401
        except ImportError:
            report(False, "job object", "pywin32 não instalado")
        else:
            if is_store_python():
                report(
                    False,
                    "job object",
                    "Python da Microsoft Store não segura os processos filhos; "
                    "recrie a venv com `uv sync` (usa o Python gerenciado pelo uv)",
                )
            else:
                report(True, "job object", "ok")

    raise typer.Exit(0 if ok else 1)


# ------------------------------------------------------------------ pipeline


def _load_or_exit(loader, path):
    try:
        return loader(path)
    except ConfigError as e:
        typer.secho(str(e), fg="red", err=True)
        raise typer.Exit(2) from e


def _pipeline(paths: ProjectPaths) -> Pipeline:
    paths.ensure_dirs()
    db.upgrade(paths.db_url)
    sessions = db.make_session_factory(db.make_engine(paths.db_url))
    return Pipeline(sessions=sessions, stop=StopFlag(paths.run_dir), log=typer.echo)


def _run_steps(name: str, steps_factory) -> None:
    """Executa etapas do pipeline como processo gerenciado (Job Object + PID registrado)."""
    paths = _paths()
    enter_managed_process(paths, name)
    profile = _load_or_exit(load_profile, paths.profile_file)
    pipeline = _pipeline(paths)
    pipeline.stop.clear()
    run = pipeline.run(steps_factory(paths, profile, pipeline))
    typer.echo(f"\nrun #{run.id}: {run.status} {run.stats}")
    if run.errors:
        typer.secho(f"{len(run.errors)} erro(s):", fg="yellow")
        for err in run.errors:
            typer.echo(f"  - {err}")
    if run.status is RunStatus.FAILED:
        raise typer.Exit(1)


def _collect_steps(paths: ProjectPaths, profile: Profile, pipeline: Pipeline):
    companies = _load_or_exit(load_companies, paths.companies_file)
    http = PoliteClient(make_client())
    sources = build_sources(http, companies, profile.preferences)
    return [
        lambda: pipeline.collect(sources, companies),
        lambda: pipeline.screen(HardFilter(profile.preferences)),
    ]


def _rank_steps(paths: ProjectPaths, profile: Profile, pipeline: Pipeline, top: int | None):
    cv_text = _load_or_exit(load_cv, paths.cv_file).as_text()
    llm_cfg = profile.llm
    embedder = OllamaEmbedder(llm_cfg.ollama_url, llm_cfg.embed_model)
    llm = OllamaLLM(llm_cfg.ollama_url, llm_cfg.local_model, think=llm_cfg.think)
    return [
        lambda: pipeline.screen(HardFilter(profile.preferences)),
        lambda: pipeline.embed_rank(embedder, cv_text),
        lambda: pipeline.llm_score(llm, profile, cv_text, top or llm_cfg.rank_top_n),
    ]


TopOption = typer.Option(None, "--top", help="Quantas vagas mandar ao LLM (padrão: profile).")


@app.command()
def collect() -> None:
    """Busca vagas novas em todas as fontes e aplica o filtro por regra."""
    _run_steps("collect", _collect_steps)


@app.command()
def rank(top: int | None = TopOption) -> None:
    """Compara as vagas filtradas com o CV (embeddings) e dá nota às melhores (LLM local)."""
    _run_steps("rank", lambda p, prof, pipe: _rank_steps(p, prof, pipe, top))


@app.command()
def run(top: int | None = TopOption) -> None:
    """Pipeline da noite: coleta + filtro + similaridade + nota do LLM."""
    _run_steps(
        "run",
        lambda p, prof, pipe: _collect_steps(p, prof, pipe) + _rank_steps(p, prof, pipe, top)[1:],
    )


@app.command()
def jobs(
    limit: int = typer.Option(20, "--limit", "-n"),
    min_score: int = typer.Option(0, "--min-score"),
) -> None:
    """Lista as vagas com nota, da melhor para a pior (até o painel existir)."""
    paths = _paths()
    pipeline = _pipeline(paths)
    with pipeline.sessions() as s:
        scores = [sc for sc in JobRepository(s).ranked(limit) if sc.llm_score >= min_score]
        if not scores:
            typer.echo("nenhuma vaga avaliada ainda; rode `night-shift run`")
            return
        for sc in scores:
            j = sc.job
            flags = f"  [!] {'; '.join(sc.red_flags)}" if sc.red_flags else ""
            typer.echo(
                f"{sc.llm_score:3d}  {j.title} — {j.company_name}"
                f"  ({j.location or '?'}, {j.work_model or '?'})"
            )
            typer.echo(f"     {sc.rationale}{flags}")
            typer.echo(f"     {j.url}\n")


@app.command()
def serve(
    port: int = typer.Option(8765, "--port", "-p"),
    open_browser: bool = typer.Option(False, "--open", help="Abre o painel no navegador."),
) -> None:
    """Sobe o painel em http://127.0.0.1:PORT (só acessível desta máquina)."""
    import threading
    import webbrowser

    import uvicorn

    from night_shift.web.app import create_app

    paths = _paths()
    enter_managed_process(paths, "serve")
    pipeline = _pipeline(paths)
    url = f"http://127.0.0.1:{port}"
    typer.echo(f"painel em {url}  (Ctrl+C para parar)")
    if open_browser:
        threading.Timer(1.0, webbrowser.open, args=[url]).start()
    uvicorn.run(create_app(pipeline.sessions), host="127.0.0.1", port=port, log_level="warning")


@db_app.command("enrich")
def db_enrich() -> None:
    """Preenche nível, contrato e salário de vagas antigas a partir do texto."""
    pipeline = _pipeline(_paths())
    with pipeline.sessions.begin() as s:
        n = JobRepository(s).enrich_existing()
    typer.echo(f"{n} vaga(s) atualizada(s)")


@companies_app.command("probe")
def companies_probe(slugs: list[str]) -> None:
    """Descobre em qual ATS (Greenhouse/Lever/Ashby) cada slug tem job board."""
    http = PoliteClient(make_client(), min_interval=0.2)
    for slug in slugs:
        found = []
        for ats, cls in ATS_SOURCES.items():
            try:
                n = sum(1 for _ in cls(http, CompanyConfig(name=slug, slug=slug)).fetch())
            except SourceError:
                continue
            if n:
                found.append(f"{ats} ({n} vagas)")
        typer.echo(f"{slug}: {', '.join(found) or 'nada encontrado'}")


if __name__ == "__main__":
    app()
