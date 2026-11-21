import json
import sys
import urllib.error
import urllib.request

import typer

from night_shift import __version__
from night_shift.adapters.storage import db
from night_shift.config import ConfigError, bootstrap_config, load_profile
from night_shift.paths import ProjectPaths
from night_shift.runtime.job_object import IS_WINDOWS, is_store_python

app = typer.Typer(
    help="night-shift: busca, avalia e se candidata a vagas enquanto você dorme.",
    no_args_is_help=True,
)
db_app = typer.Typer(help="Banco de dados (SQLite + Alembic).", no_args_is_help=True)
app.add_typer(db_app, name="db")


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

    ollama_url = profile.llm.ollama_url if profile else "http://localhost:11434"
    try:
        with urllib.request.urlopen(f"{ollama_url}/api/tags", timeout=2) as resp:
            models = [m["name"] for m in json.load(resp).get("models", [])]
        report(True, "ollama", ", ".join(models) or "rodando, sem modelos baixados")
    except (urllib.error.URLError, OSError, ValueError):
        # Ollama só é necessário a partir da Fase 1; não reprova o doctor.
        typer.echo(f"[{typer.style('warn', fg='yellow')}] ollama: não encontrado em {ollama_url}")

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


if __name__ == "__main__":
    app()
