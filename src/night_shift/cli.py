import json
import os
import sys
import urllib.error
import urllib.request
from datetime import time as dt_time
from pathlib import Path

import typer

from night_shift import __version__
from night_shift.adapters.llm.claude_cli import ClaudeCLI, find_executable
from night_shift.adapters.llm.ollama import OllamaEmbedder, OllamaLLM
from night_shift.adapters.render.cv_pdf import render_cv_pdf
from night_shift.adapters.scheduler.windows_task import ON_DEMAND_TASK, WindowsTaskScheduler
from night_shift.adapters.sources import build_sources
from night_shift.adapters.sources.ats import ATS_SOURCES
from night_shift.adapters.sources.http import PoliteClient, make_client
from night_shift.adapters.storage import db
from night_shift.adapters.storage.documents import DocumentsRepository
from night_shift.adapters.storage.repository import JobRepository
from night_shift.application.keywords import KeywordEmbedder
from night_shift.application.pipeline import Pipeline
from night_shift.config import (
    AutomationConfig,
    CompanyConfig,
    ConfigError,
    LLMConfig,
    Profile,
    TurnOffConfig,
    bootstrap_config,
    load_companies,
    load_cv,
    load_profile,
)
from night_shift.domain.cv import default_cv, translation_problems
from night_shift.domain.enums import RunStatus
from night_shift.domain.filters import HardFilter
from night_shift.paths import ProjectPaths
from night_shift.ports import SourceError
from night_shift.runtime.job_object import IS_WINDOWS, is_store_python
from night_shift.runtime.lifecycle import enter_managed_process, running_pipeline
from night_shift.runtime.logs import open_run_log, tee
from night_shift.runtime.pids import PidRegistry
from night_shift.runtime.shortcuts import create_desktop_shortcuts
from night_shift.runtime.stop_flag import StopFlag
from night_shift.runtime.turn_off import stop_ollama, turn_off, turn_on

app = typer.Typer(
    help="night-shift: busca, avalia e se candidata a vagas enquanto você dorme.",
    no_args_is_help=True,
)
db_app = typer.Typer(help="Banco de dados (SQLite + Alembic).", no_args_is_help=True)
app.add_typer(db_app, name="db")
companies_app = typer.Typer(help="Empresas-alvo.", no_args_is_help=True)
app.add_typer(companies_app, name="companies")
schedule_app = typer.Typer(help="Tarefa diária no Agendador do Windows.", no_args_is_help=True)
app.add_typer(schedule_app, name="schedule")
cv_app = typer.Typer(help="CV mestre: PDFs completos e checagem da tradução.", no_args_is_help=True)
app.add_typer(cv_app, name="cv")


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

    # O LLM só é exigido pelo `rank`; a coleta funciona sem ele, então aqui é só aviso.
    def warn(label: str, detail: str) -> None:
        typer.echo(f"[{typer.style('warn', fg='yellow')}] {label}: {detail}")

    llm = profile.llm if profile else LLMConfig()
    if llm.provider == "claude":
        exe = find_executable(llm.claude_executable)
        if exe:
            report(True, "claude cli", f"{exe} (modelo {llm.claude_model})")
        else:
            warn("claude cli", "não encontrado; `winget install Anthropic.ClaudeCode` e `claude`")
    else:
        _check_ollama(llm, report, warn)

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


def _check_ollama(llm: LLMConfig, report, warn) -> None:
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
    """Executa etapas do pipeline como processo gerenciado (Job Object + PID registrado),
    uma execução por vez, com log em ``logs/``."""
    paths = _paths()
    other = running_pipeline(paths)
    if other is not None:
        msg = (
            f"já tem um `{other.name}` rodando (PID {other.pid}); espere terminar ou use "
            "`night-shift off`"
        )
        # Vai para o log também: a tarefa agendada roda sem ninguém vendo o terminal.
        with open_run_log(paths.logs_dir, f"{name}-recusado") as logfile:
            tee(lambda m: typer.secho(m, fg="yellow", err=True), logfile)(msg)
        raise typer.Exit(3)
    enter_managed_process(paths, name)
    profile = _load_or_exit(load_profile, paths.profile_file)
    pipeline = _pipeline(paths)
    with open_run_log(paths.logs_dir, name) as logfile:
        pipeline.log = tee(typer.echo, logfile)
        pipeline.log_path = logfile.name
        pipeline.stop.clear()
        run = pipeline.run(steps_factory(paths, profile, pipeline))
        pipeline.log(f"\nrun #{run.id}: {run.status} {run.stats}")
        if run.errors:
            pipeline.log(f"{len(run.errors)} erro(s):")
            for err in run.errors:
                pipeline.log(f"  - {err}")
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


def _llm_and_embedder(llm_cfg: LLMConfig, cv_text: str):
    if llm_cfg.provider == "ollama":
        return (
            OllamaLLM(llm_cfg.ollama_url, llm_cfg.local_model, think=llm_cfg.think),
            OllamaEmbedder(llm_cfg.ollama_url, llm_cfg.embed_model),
        )
    return (
        ClaudeCLI(llm_cfg.claude_model, executable=llm_cfg.claude_executable),
        KeywordEmbedder(cv_text),
    )


def _rank_steps(
    paths: ProjectPaths,
    profile: Profile,
    pipeline: Pipeline,
    top: int | None,
    budget_minutes: int | None,
):
    cv_text = _load_or_exit(load_cv, paths.cv_file).as_text()
    llm_cfg = profile.llm
    llm, embedder = _llm_and_embedder(llm_cfg, cv_text)
    minutes = budget_minutes or llm_cfg.time_budget_minutes
    return [
        lambda: pipeline.screen(HardFilter(profile.preferences)),
        lambda: pipeline.embed_rank(embedder, cv_text),
        lambda: pipeline.llm_score(
            llm,
            profile,
            cv_text,
            top or llm_cfg.rank_top_n,
            budget_seconds=minutes * 60 if minutes else None,
        ),
    ]


def _docs_steps(paths: ProjectPaths, profile: Profile, pipeline: Pipeline, limit: int | None):
    cv = _load_or_exit(load_cv, paths.cv_file)
    llm_cfg = profile.llm
    if llm_cfg.provider == "ollama":
        llm = OllamaLLM(llm_cfg.ollama_url, llm_cfg.local_model, think=llm_cfg.think)
    else:
        llm = ClaudeCLI(llm_cfg.documents_model, executable=llm_cfg.claude_executable)
    minutes = llm_cfg.time_budget_minutes

    def render(tailored, out, lang="pt"):
        return render_cv_pdf(tailored, profile.name, profile.email, out, lang)

    return [
        lambda: pipeline.documents(
            llm,
            profile,
            cv,
            render,
            paths.cv_output_dir,
            llm_cfg.documents_min_score,
            limit or llm_cfg.claude_daily_letters,
            budget_seconds=minutes * 60 if minutes else None,
            cv_en=load_cv(paths.cv_en_file) if paths.cv_en_file.exists() else None,
        )
    ]


TopOption = typer.Option(None, "--top", help="Quantas vagas mandar ao LLM (padrão: profile).")
BudgetOption = typer.Option(
    None, "--time-budget", help="Minutos máximos da etapa de nota (padrão: profile, 120)."
)


@app.command()
def collect() -> None:
    """Busca vagas novas em todas as fontes e aplica o filtro por regra."""
    _run_steps("collect", _collect_steps)


@app.command()
def rank(
    top: int | None = TopOption,
    time_budget: int | None = BudgetOption,
    rescore: bool = typer.Option(
        False, "--rescore", help="Apaga as notas de vagas sem decisão e avalia de novo."
    ),
) -> None:
    """Ordena as vagas filtradas pela semelhança com o CV e dá nota às melhores com o LLM."""
    if rescore:
        with _pipeline(_paths()).sessions.begin() as s:
            typer.echo(f"{JobRepository(s).reset_llm_scores()} nota(s) apagada(s) para reavaliar")
    _run_steps("rank", lambda p, prof, pipe: _rank_steps(p, prof, pipe, top, time_budget))


@app.command()
def docs(
    limit: int | None = typer.Option(
        None, "--limit", "-n", help="Máximo de vagas (padrão: llm.claude_daily_letters)."
    ),
    regenerate: bool = typer.Option(
        False, "--regenerate", help="Apaga CV ajustado e carta das vagas na fila e gera de novo."
    ),
) -> None:
    """Gera CV ajustado (PDF) e carta para as melhores vagas da fila."""
    if regenerate:
        with _pipeline(_paths()).sessions.begin() as s:
            typer.echo(f"{DocumentsRepository(s).clear_documents()} vaga(s) para gerar de novo")
    _run_steps("docs", lambda p, prof, pipe: _docs_steps(p, prof, pipe, limit))


def _outreach_steps(paths: ProjectPaths, profile: Profile, pipeline: Pipeline, limit: int | None):
    from night_shift.adapters.contacts import ContactFinder

    cv = _load_or_exit(load_cv, paths.cv_file)
    companies = _load_or_exit(load_companies, paths.companies_file)
    llm_cfg = profile.llm
    if llm_cfg.provider == "ollama":
        llm = OllamaLLM(llm_cfg.ollama_url, llm_cfg.local_model, think=llm_cfg.think)
    else:
        llm = ClaudeCLI(llm_cfg.documents_model, executable=llm_cfg.claude_executable)
    finder = ContactFinder(PoliteClient(make_client(), min_interval=0.5))
    minutes = llm_cfg.time_budget_minutes

    def sync():
        with pipeline.sessions.begin() as s:
            JobRepository(s).sync_companies(companies)

    return [
        sync,
        lambda: pipeline.discover_contacts(finder),
        lambda: pipeline.outreach(
            llm,
            profile,
            cv,
            limit if limit is not None else llm_cfg.claude_daily_outreach,
            budget_seconds=minutes * 60 if minutes else None,
        ),
    ]


@app.command()
def outreach(
    limit: int | None = typer.Option(
        None, "--limit", "-n", help="Máximo de mensagens hoje (padrão: llm.claude_daily_outreach)."
    ),
) -> None:
    """Varre os sites das empresas (contato de RH, carreiras) e escreve mensagens de outreach
    (nota do LinkedIn + e-mail). Nada é enviado: tudo fica na aba Outreach do painel."""
    _run_steps("outreach", lambda p, prof, pipe: _outreach_steps(p, prof, pipe, limit))


@app.command()
def run(top: int | None = TopOption, time_budget: int | None = BudgetOption) -> None:
    """Pipeline da noite: coleta, filtro, similaridade, nota do LLM, CV ajustado e carta.

    O limite de tempo vale para as etapas de LLM juntas (nota + documentos)."""
    _run_steps(
        "run",
        lambda p, prof, pipe: (
            _collect_steps(p, prof, pipe)
            + _rank_steps(p, prof, pipe, top, time_budget)[1:]
            + _docs_steps(p, prof, pipe, None)
            + _outreach_steps(p, prof, pipe, None)
        ),
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


def _start_on_demand(paths: ProjectPaths) -> str:
    """Botão 'Buscar vagas' do painel. Dispara a tarefa ``\\NightShift\\OnDemand``, que não
    tem horário (nunca roda sozinha) e é independente da noturna: funciona mesmo com a busca
    automática desligada. Roda fora do processo do painel, então fechar o painel não mata a
    busca; o `off` mata, porque a busca se registra como qualquer execução."""
    other = running_pipeline(paths)
    if other is not None:
        return f"Já tem um `{other.name}` rodando (PID {other.pid})."
    launcher = WindowsTaskScheduler(ON_DEMAND_TASK)
    status = launcher.status()
    if not status.installed:
        launcher.install(_venv_exe(), "run", paths.root, at=None)
    elif not status.enabled:
        launcher.enable()
    StopFlag(paths.run_dir).clear()
    launcher.run_now()
    return "Busca iniciada; os números aparecem em alguns segundos."


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
    try:
        prof = load_profile(paths.profile_file)
        threshold, daily_outreach = (
            prof.automation.auto_apply_min_score,
            prof.llm.claude_daily_outreach,
        )
    except ConfigError:
        threshold, daily_outreach = AutomationConfig().auto_apply_min_score, 10
    scheduler = _scheduler()

    def turn_everything_off() -> list[str]:
        report = turn_off(
            paths, scheduler, _grace_seconds(paths), ollama=_ollama_stopper(paths), log=typer.echo
        )
        # O painel se desliga por último, depois de devolver o relatório para o navegador.
        PidRegistry(paths.run_dir).unregister()
        threading.Timer(1.5, os._exit, args=[0]).start()
        return report.lines()

    web_app = create_app(
        pipeline.sessions,
        auto_threshold=threshold,
        cv_dir=paths.cv_output_dir,
        shots_dir=paths.shots_dir,
        schedule_status=(lambda: scheduler.status().describe()) if scheduler else None,
        on_turn_off=turn_everything_off,
        logs_dir=paths.logs_dir,
        request_stop=StopFlag(paths.run_dir).request,
        start_run=(lambda: _start_on_demand(paths)) if scheduler else None,
        outreach_daily_limit=daily_outreach,
    )
    uvicorn.run(web_app, host="127.0.0.1", port=port, log_level="warning")


@db_app.command("enrich")
def db_enrich() -> None:
    """Preenche nível, contrato e salário de vagas antigas a partir do texto."""
    pipeline = _pipeline(_paths())
    with pipeline.sessions.begin() as s:
        n = JobRepository(s).enrich_existing()
    typer.echo(f"{n} vaga(s) atualizada(s)")


# ----------------------------------------------------------- aplicação assistida


@app.command()
def apply(
    limit: int = typer.Option(5, "--limit", "-n", help="Máximo de vagas nesta sessão."),
    job: int | None = typer.Option(
        None, "--job", help="Uma vaga específica (qualquer fila; só Greenhouse/Lever/Ashby)."
    ),
    preview: bool = typer.Option(
        False,
        "--preview",
        help="Só preenche e tira print, com o navegador invisível; você não envia nada.",
    ),
) -> None:
    """Aplicação assistida: abre cada vaga da fila automática já preenchida (dados, CV
    ajustado e carta). Você confere, completa o que faltar e clica em enviar; o sistema
    reconhece a confirmação e marca a vaga como aplicada. Nunca envia sozinho."""
    from night_shift.adapters.applier.assisted import AssistedApplier, apply_url
    from night_shift.adapters.storage.applications import ApplyRepository
    from night_shift.application.apply import build_candidate

    paths = _paths()
    enter_managed_process(paths, "apply")
    profile = _load_or_exit(load_profile, paths.profile_file)
    cv = _load_or_exit(load_cv, paths.cv_file)
    pipeline = _pipeline(paths)
    stop = StopFlag(paths.run_dir)
    stop.clear()
    threshold = profile.automation.auto_apply_min_score

    with pipeline.sessions() as s:
        repo = ApplyRepository(s, threshold)
        if job is not None:
            chosen = repo.one(job)
            if chosen is None:
                typer.secho("vaga não encontrada ou não é Greenhouse/Lever/Ashby", fg="red")
                raise typer.Exit(2)
            scores = [chosen]
        else:
            room = profile.automation.daily_auto_apply_limit - repo.applied_today()
            if room <= 0 and not preview:
                typer.echo(
                    "limite diário de aplicações atingido (automation.daily_auto_apply_limit)"
                )
                return
            scores = repo.ready(min(limit, room) if not preview else limit)
        plan = []
        for sc in scores:
            j, app_row = sc.job, sc.job.application
            url = apply_url(j.source, j.company.ats_slug if j.company else None, j.external_id)
            cv_path = app_row.cv_variant_path if app_row else None
            plan.append(
                (j.id, j.title, j.company_name, url, cv_path, app_row and app_row.cover_letter)
            )

    if not plan:
        typer.echo(
            "nada pronto na fila automática (precisa de nota >= "
            f"{threshold}, sem alertas, e CV ajustado: rode `night-shift docs`)"
        )
        return

    mode = "prévia (sem enviar)" if preview else "assistida: você confere e envia"
    typer.echo(f"{len(plan)} vaga(s), modo {mode}")
    results: dict[str, int] = {}
    with AssistedApplier(
        paths.browser_profile_dir,
        paths.shots_dir,
        headless=preview,
        wait_minutes=profile.application.wait_minutes,
    ) as applier:
        for n, (job_id, title, company, url, cv_path, letter) in enumerate(plan, 1):
            if stop.is_set():
                typer.echo("parada solicitada")
                break
            typer.echo(f"[{n}/{len(plan)}] {title} — {company}")
            if url is None or not cv_path:
                typer.echo("  pulada: sem URL do formulário ou sem CV ajustado")
                continue
            cand = build_candidate(profile, cv, Path(cv_path), letter)
            outcome = applier.apply(job_id, url, cand, preview=preview)
            with pipeline.sessions.begin() as s:
                ApplyRepository(s, threshold).save_outcome(
                    job_id, outcome.as_dict(), applied=outcome.status == "applied"
                )
            results[outcome.status] = results.get(outcome.status, 0) + 1
            r = outcome.report
            detail = (
                f"{len(r.filled)} preenchido(s), "
                f"CV {'anexado' if r.resume_attached else 'NÃO anexado'}, "
                f"{len(r.unanswered_required)} obrigatório(s) para você, "
                f"{len(r.sensitive_skipped)} sensível(is) não tocado(s)"
                + (f", captcha {r.captcha}" if r.captcha else "")
                if r
                else outcome.message
            )
            typer.echo(f"  {outcome.status}: {detail}")
    typer.echo(f"resumo: {results}")


# ------------------------------------------------------- agendamento e turn-off


def _venv_exe() -> Path:
    """O ``night-shift.exe`` da venv atual (é o que a tarefa e os atalhos executam)."""
    return Path(sys.executable).parent / "night-shift.exe"


def _scheduler() -> WindowsTaskScheduler | None:
    return WindowsTaskScheduler() if IS_WINDOWS else None


def _parse_time(value: str) -> dt_time:
    try:
        return dt_time.fromisoformat(value)
    except ValueError as e:
        raise typer.BadParameter("use HH:MM, ex.: 02:00") from e


@schedule_app.command("install")
def schedule_install(
    at: str = typer.Option("02:00", "--at", help="Horário diário (HH:MM)."),
    max_hours: int = typer.Option(3, "--max-hours", help="Tempo máximo de uma execução."),
) -> None:
    """Cria (ou atualiza) a tarefa diária `night-shift run` no Agendador do Windows."""
    scheduler = _scheduler()
    if scheduler is None:
        typer.secho("agendamento só no Windows", fg="red", err=True)
        raise typer.Exit(2)
    paths = _paths()
    exe = _venv_exe()
    scheduler.install(exe, "run", paths.root, _parse_time(at), max_hours)
    StopFlag(paths.run_dir).clear()
    typer.echo(f"agendado: {scheduler.status().describe()}")
    typer.echo(f"  comando: {exe} run   (pasta {paths.root})")
    typer.echo(f"  logs em: {paths.logs_dir}")


@schedule_app.command("status")
def schedule_status() -> None:
    """Mostra se a tarefa diária existe, está ligada e o horário."""
    scheduler = _scheduler()
    typer.echo(scheduler.status().describe() if scheduler else "agendamento só no Windows")


@schedule_app.command("remove")
def schedule_remove() -> None:
    """Apaga a tarefa diária (e a sob demanda do botão 'Buscar vagas')."""
    scheduler = _scheduler()
    removed = scheduler.remove() if scheduler else False
    if scheduler is not None:
        WindowsTaskScheduler(ON_DEMAND_TASK).remove()
    typer.echo("tarefa removida" if removed else "não havia tarefa agendada")


@schedule_app.command("disable")
def schedule_disable() -> None:
    """Desliga só a busca automática diária (o painel e o botão 'Buscar vagas' seguem
    funcionando). Religue com `schedule enable`."""
    scheduler = _scheduler()
    ok = scheduler.disable() if scheduler else False
    typer.echo(f"busca automática: {scheduler.status().describe()}" if ok else "não há tarefa")


@schedule_app.command("enable")
def schedule_enable() -> None:
    """Religa a busca automática diária."""
    scheduler = _scheduler()
    ok = scheduler.enable() if scheduler else False
    typer.echo(f"busca automática: {scheduler.status().describe()}" if ok else "não há tarefa")


@schedule_app.command("run-now")
def schedule_run_now() -> None:
    """Dispara a tarefa agendada agora (testa o mesmo caminho da execução da noite)."""
    scheduler = _scheduler()
    if scheduler is None or not scheduler.status().installed:
        typer.secho("não há tarefa agendada; rode `night-shift schedule install`", fg="red")
        raise typer.Exit(2)
    scheduler.run_now()
    typer.echo(f"disparada; acompanhe em {_paths().logs_dir}")


def _ollama_stopper(paths: ProjectPaths):
    try:
        profile = load_profile(paths.profile_file)
    except ConfigError:
        return lambda: None
    llm, off_cfg = profile.llm, profile.turn_off
    if llm.provider != "ollama" and not off_cfg.stop_ollama:
        return lambda: None
    return lambda: stop_ollama(llm.local_model, kill_server=off_cfg.stop_ollama)


def _grace_seconds(paths: ProjectPaths) -> int:
    try:
        return load_profile(paths.profile_file).turn_off.grace_seconds
    except ConfigError:
        return TurnOffConfig().grace_seconds


@app.command()
def off(
    grace: int | None = typer.Option(
        None, "--grace", help="Segundos para o pipeline parar sozinho (padrão: profile, 30)."
    ),
) -> None:
    """Desliga TUDO do night-shift: pipeline, painel, processos filhos e a tarefa agendada."""
    paths = _paths()
    report = turn_off(
        paths,
        _scheduler(),
        grace if grace is not None else _grace_seconds(paths),
        ollama=_ollama_stopper(paths),
        log=typer.echo,
    )
    for line in report.lines():
        typer.echo(f"- {line}")
    typer.echo("pronto. Para religar: night-shift on")
    if report.survivors:
        raise typer.Exit(1)


@app.command()
def on() -> None:
    """Religa a tarefa agendada e libera o pipeline depois de um `off`."""
    had_task = turn_on(_paths(), _scheduler())
    status = _scheduler().status().describe() if had_task else "sem tarefa agendada"
    typer.echo(f"ligado ({status})")
    if not had_task:
        typer.echo("para agendar: night-shift schedule install --at 02:00")


@app.command()
def shortcuts() -> None:
    """Cria na área de trabalho os atalhos 'night-shift OFF', 'ON' e 'Painel'."""
    if not IS_WINDOWS:
        typer.secho("atalhos só no Windows", fg="red", err=True)
        raise typer.Exit(2)
    paths = _paths()
    created = create_desktop_shortcuts(_venv_exe(), paths.root)
    for path in created:
        typer.echo(f"criado: {path}")


@cv_app.command("check")
def cv_check() -> None:
    """Valida o CV mestre e confere se a tradução em inglês bate com ele (mesmos IDs)."""
    paths = _paths()
    cv = _load_or_exit(load_cv, paths.cv_file)
    bullets = sum(len(e.bullets) for e in cv.experiences)
    typer.echo(f"cv_master.yaml: {len(cv.experiences)} experiência(s), {bullets} bullets")
    if not paths.cv_en_file.exists():
        typer.echo("cv_master.en.yaml: não existe (vagas em inglês usam o CV em português)")
        return
    problems = translation_problems(cv, _load_or_exit(load_cv, paths.cv_en_file))
    if problems:
        typer.secho("cv_master.en.yaml NÃO bate com o mestre:", fg="red")
        for p in problems:
            typer.echo(f"  - {p}")
        raise typer.Exit(1)
    typer.echo("cv_master.en.yaml: ok, mesmos IDs e habilidades")


@cv_app.command("pdf")
def cv_pdf() -> None:
    """Gera o CV completo (sem ajuste por vaga) em PDF, em português e em inglês, para
    anexar nas aplicações manuais: output/cv/curriculo.pdf e output/cv/resume-en.pdf."""
    paths = _paths()
    profile = _load_or_exit(load_profile, paths.profile_file)
    versions = [("pt", paths.cv_file, "curriculo.pdf")]
    if paths.cv_en_file.exists():
        versions.append(("en", paths.cv_en_file, "resume-en.pdf"))
    for lang, source, filename in versions:
        cv = _load_or_exit(load_cv, source)
        out = render_cv_pdf(
            default_cv(cv), profile.name, profile.email, paths.cv_output_dir / filename, lang
        )
        typer.echo(f"gerado: {out}")


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
