"""Dados da página /ao-vivo: a execução atual (ou a última) vista de perto."""

from datetime import UTC, datetime
from pathlib import Path

from night_shift.adapters.storage.models import Run
from night_shift.adapters.storage.review import ReviewRepository
from night_shift.domain.enums import RunStatus

STAGES = [
    ("coleta", "Coleta"),
    ("filtro", "Filtro"),
    ("similaridade", "Similaridade"),
    ("nota", "Nota do LLM"),
    ("documentos", "CV e carta"),
    ("contatos", "Contatos"),
    ("outreach", "Outreach"),
]

COUNTERS = [
    ("collected", "coletadas"),
    ("new", "novas"),
    ("passed_filter", "passaram no filtro"),
    ("llm_scored", "com nota"),
    ("documents", "CV + carta"),
    ("outreach", "mensagens de outreach"),
    ("llm_deferred", "ficaram p/ depois"),
]

TAIL_BYTES = 12_000


def _aware(dt: datetime | None) -> datetime | None:
    if dt is None:
        return None
    return dt if dt.tzinfo else dt.replace(tzinfo=UTC)


def clock(seconds: float | None) -> str:
    if seconds is None:
        return "—"
    seconds = max(0, int(seconds))
    h, rest = divmod(seconds, 3600)
    m, s = divmod(rest, 60)
    return f"{h}h{m:02d}min" if h else f"{m}min {s:02d}s"


def tail_log(path: str | None, logs_dir: Path | None, lines: int = 25) -> list[str]:
    """Últimas linhas do log da execução, só se o arquivo estiver dentro de ``logs/``."""
    if not path or logs_dir is None:
        return []
    file = Path(path).resolve()
    if not file.is_relative_to(logs_dir.resolve()) or not file.exists():
        return []
    with file.open("rb") as f:
        f.seek(0, 2)
        size = f.tell()
        f.seek(max(0, size - TAIL_BYTES))
        text = f.read().decode("utf-8", errors="replace")
    return [line for line in text.splitlines() if line.strip()][-lines:]


def live_context(repo: ReviewRepository, logs_dir: Path | None, now: datetime | None = None):
    now = now or datetime.now(UTC)
    run: Run | None = repo.latest_run()
    if run is None:
        return {"run": None, "running": False}

    running = run.status is RunStatus.RUNNING
    started = _aware(run.started_at)
    finished = _aware(run.finished_at)
    ends = _aware(run.budget_ends_at)
    stage_keys = [k for k, _ in STAGES]
    current = stage_keys.index(run.stage) if run.stage in stage_keys else -1

    return {
        "run": run,
        "running": running,
        "stages": [
            {
                "label": label,
                "state": (
                    "done"
                    if i < current or (not running and i <= current)
                    else "active"
                    if i == current
                    else "todo"
                ),
            }
            for i, (_, label) in enumerate(STAGES)
        ],
        "counters": [(label, (run.stats or {}).get(key, 0)) for key, label in COUNTERS],
        "elapsed": clock(((finished or now) - started).total_seconds()),
        "remaining": clock((ends - now).total_seconds()) if ends and running else None,
        "log_lines": tail_log(run.log_path, logs_dir),
        "recent": repo.scored_since(run.started_at),
    }
