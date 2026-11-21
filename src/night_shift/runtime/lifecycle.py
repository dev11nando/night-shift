import atexit
import os

from night_shift.paths import ProjectPaths
from night_shift.runtime.job_object import JobObject
from night_shift.runtime.pids import PidEntry, PidRegistry

# Referência global de propósito: se o JobObject fosse coletado pelo GC, o handle
# fecharia e o Windows mataria o próprio processo.
_job = JobObject()


PIPELINE_COMMANDS = frozenset({"run", "collect", "rank", "docs"})


def running_pipeline(paths: ProjectPaths) -> PidEntry | None:
    """Outro comando do pipeline em execução (para não rodarem dois ao mesmo tempo)."""
    me = os.getpid()
    for entry in PidRegistry(paths.run_dir).alive():
        if entry.name in PIPELINE_COMMANDS and entry.pid != me:
            return entry
    return None


def enter_managed_process(paths: ProjectPaths, name: str) -> bool:
    """Chamar no início de todo comando de longa duração (run, serve).

    Coloca o processo no Job Object e o registra em ``run/pids.json``.
    Retorna se o Job Object está ativo.
    """
    registry = PidRegistry(paths.run_dir)
    registry.register(name)
    atexit.register(registry.unregister)
    return _job.adopt_current_process()
