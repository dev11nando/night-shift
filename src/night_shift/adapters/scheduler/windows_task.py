"""Tarefa noturna no Agendador de Tarefas do Windows, via ``schtasks.exe``.

A tarefa é criada a partir de um XML (e não de ``/TR``) para poder definir pasta de
trabalho, acordar o PC do modo de suspensão, rodar mesmo na bateria, recuperar uma
execução perdida (PC desligado no horário) e um tempo máximo. Roda só com o usuário
logado (``InteractiveToken``), então não precisa de senha nem de administrador.
"""

import re
import subprocess
import tempfile
from collections.abc import Callable
from dataclasses import dataclass
from datetime import date, time
from pathlib import Path
from xml.sax.saxutils import escape

TASK_NAME = r"\NightShift\Nightly"

Runner = Callable[[list[str]], subprocess.CompletedProcess]


class SchedulerError(Exception):
    pass


def _run(args: list[str]) -> subprocess.CompletedProcess:
    # schtasks escreve na página de código OEM do console (cp850 em pt-BR).
    return subprocess.run(args, capture_output=True, text=True, encoding="cp850", errors="replace")


@dataclass(frozen=True)
class ScheduleStatus:
    installed: bool
    enabled: bool = False
    at: time | None = None

    def describe(self) -> str:
        if not self.installed:
            return "não agendado"
        hour = self.at.strftime("%H:%M") if self.at else "?"
        return f"todo dia às {hour}" + ("" if self.enabled else " (desligado)")


def build_task_xml(
    executable: Path, arguments: str, workdir: Path, at: time, max_hours: int = 3
) -> str:
    start = f"{date.today().isoformat()}T{at.strftime('%H:%M')}:00"
    return f"""<?xml version="1.0" encoding="UTF-16"?>
<Task version="1.4" xmlns="http://schemas.microsoft.com/windows/2004/02/mit/task">
  <RegistrationInfo>
    <Description>night-shift: coleta, avalia e prepara candidaturas durante a noite.</Description>
  </RegistrationInfo>
  <Triggers>
    <CalendarTrigger>
      <StartBoundary>{start}</StartBoundary>
      <Enabled>true</Enabled>
      <ScheduleByDay><DaysInterval>1</DaysInterval></ScheduleByDay>
    </CalendarTrigger>
  </Triggers>
  <Principals>
    <Principal id="Author">
      <LogonType>InteractiveToken</LogonType>
      <RunLevel>LeastPrivilege</RunLevel>
    </Principal>
  </Principals>
  <Settings>
    <MultipleInstancesPolicy>IgnoreNew</MultipleInstancesPolicy>
    <DisallowStartIfOnBatteries>false</DisallowStartIfOnBatteries>
    <StopIfGoingOnBatteries>false</StopIfGoingOnBatteries>
    <StartWhenAvailable>true</StartWhenAvailable>
    <WakeToRun>true</WakeToRun>
    <ExecutionTimeLimit>PT{max_hours}H</ExecutionTimeLimit>
    <Enabled>true</Enabled>
    <Hidden>false</Hidden>
  </Settings>
  <Actions Context="Author">
    <Exec>
      <Command>{escape(str(executable))}</Command>
      <Arguments>{escape(arguments)}</Arguments>
      <WorkingDirectory>{escape(str(workdir))}</WorkingDirectory>
    </Exec>
  </Actions>
</Task>
"""


class WindowsTaskScheduler:
    def __init__(self, name: str = TASK_NAME, runner: Runner = _run) -> None:
        self.name = name
        self._runner = runner

    def _schtasks(self, *args: str, check: bool = True) -> subprocess.CompletedProcess:
        proc = self._runner(["schtasks.exe", *args])
        if check and proc.returncode != 0:
            raise SchedulerError((proc.stderr or proc.stdout).strip() or f"exit {proc.returncode}")
        return proc

    def install(
        self, executable: Path, arguments: str, workdir: Path, at: time, max_hours: int = 3
    ) -> None:
        xml = build_task_xml(executable, arguments, workdir, at, max_hours)
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "night-shift-task.xml"
            path.write_text(xml, encoding="utf-16")
            self._schtasks("/Create", "/TN", self.name, "/XML", str(path), "/F")

    def status(self) -> ScheduleStatus:
        proc = self._schtasks("/Query", "/TN", self.name, "/XML", check=False)
        if proc.returncode != 0:
            return ScheduleStatus(installed=False)
        xml = proc.stdout
        # O <Enabled> de <Settings> é o que liga/desliga a tarefa inteira.
        settings = re.search(r"<Settings>.*?</Settings>", xml, re.DOTALL)
        enabled_m = re.search(r"<Enabled>(\w+)</Enabled>", settings.group(0)) if settings else None
        start = re.search(r"<StartBoundary>[^<]*T(\d{2}):(\d{2})", xml)
        return ScheduleStatus(
            installed=True,
            enabled=enabled_m is None or enabled_m.group(1).lower() == "true",
            at=time(int(start.group(1)), int(start.group(2))) if start else None,
        )

    def enable(self) -> bool:
        """Liga a tarefa. Retorna False se ela não existe."""
        if not self.status().installed:
            return False
        self._schtasks("/Change", "/TN", self.name, "/ENABLE")
        return True

    def disable(self) -> bool:
        """Desliga a tarefa (não roda até `enable`). Retorna False se ela não existe."""
        if not self.status().installed:
            return False
        self._schtasks("/Change", "/TN", self.name, "/DISABLE")
        return True

    def remove(self) -> bool:
        if not self.status().installed:
            return False
        self._schtasks("/Delete", "/TN", self.name, "/F")
        return True

    def run_now(self) -> None:
        self._schtasks("/Run", "/TN", self.name)
