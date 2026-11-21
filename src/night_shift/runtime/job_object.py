"""Job Object do Windows com ``KILL_ON_JOB_CLOSE``.

O processo do night-shift entra no job logo ao iniciar. Todo filho (Chromium do
Playwright, workers, uvicorn) herda o job automaticamente, e quando o último handle
do job fecha (o processo principal termina ou morre), o Windows mata a árvore inteira.
Assim não sobra processo órfão.

Fora do Windows é no-op: lá o ``off`` usa só ``kill_tree``.
"""

import sys
from typing import Any

IS_WINDOWS = sys.platform == "win32"


def is_store_python() -> bool:
    """Python da Microsoft Store: filhos escapam do Job Object (breakaway do pacote AppX)."""
    base = getattr(sys, "_base_executable", sys.executable)
    return IS_WINDOWS and "WindowsApps" in base


class JobObject:
    def __init__(self) -> None:
        self._handle: Any = None

    @property
    def active(self) -> bool:
        return self._handle is not None

    def adopt_current_process(self) -> bool:
        """Cria o job e coloca o processo atual nele. Retorna False se não suportado."""
        if not IS_WINDOWS or self.active:
            return self.active

        import win32api
        import win32job

        job = win32job.CreateJobObject(None, "")
        info = win32job.QueryInformationJobObject(job, win32job.JobObjectExtendedLimitInformation)
        info["BasicLimitInformation"]["LimitFlags"] |= win32job.JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE
        win32job.SetInformationJobObject(job, win32job.JobObjectExtendedLimitInformation, info)
        # Windows 8+ suporta jobs aninhados, então funciona mesmo dentro do job do terminal.
        win32job.AssignProcessToJobObject(job, win32api.GetCurrentProcess())
        self._handle = job
        return True

    def close(self) -> None:
        """Fecha o handle: mata todos os processos do job, inclusive o atual."""
        if self._handle is not None:
            import win32api

            handle, self._handle = self._handle, None
            win32api.CloseHandle(handle)
