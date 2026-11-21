"""Um arquivo de log por execução em ``logs/`` (gitignored), além da saída no terminal.

Essencial para a tarefa agendada, que roda sem ninguém olhando.
"""

from collections.abc import Callable
from datetime import datetime
from pathlib import Path
from typing import TextIO

KEEP_LAST = 60


def open_run_log(logs_dir: Path, name: str, now: datetime | None = None) -> TextIO:
    logs_dir.mkdir(parents=True, exist_ok=True)
    stamp = (now or datetime.now()).strftime("%Y%m%d-%H%M%S")
    prune(logs_dir)
    return (logs_dir / f"{stamp}-{name}.log").open("a", encoding="utf-8", buffering=1)


def prune(logs_dir: Path, keep: int = KEEP_LAST) -> None:
    """Apaga os logs mais antigos, mantendo os ``keep`` mais recentes."""
    files = sorted(logs_dir.glob("*.log"))
    for old in files[: max(0, len(files) - keep)]:
        old.unlink(missing_ok=True)


def tee(echo: Callable[[str], None], file: TextIO) -> Callable[[str], None]:
    def log(message: str) -> None:
        echo(message)
        file.write(f"{datetime.now():%H:%M:%S} {message}\n")

    return log
