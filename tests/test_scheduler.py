import subprocess
from datetime import time
from pathlib import Path

from night_shift.adapters.scheduler.windows_task import (
    ScheduleStatus,
    WindowsTaskScheduler,
    build_task_xml,
)

QUERY_XML = """<?xml version="1.0" encoding="UTF-16"?>
<Task version="1.4" xmlns="http://schemas.microsoft.com/windows/2004/02/mit/task">
  <Triggers><CalendarTrigger>
    <StartBoundary>2026-11-21T02:30:00</StartBoundary><Enabled>true</Enabled>
  </CalendarTrigger></Triggers>
  <Settings>
    <IdleSettings><StopOnIdleEnd>true</StopOnIdleEnd></IdleSettings>
    <Enabled>{enabled}</Enabled>
  </Settings>
</Task>"""


class FakeSchtasks:
    def __init__(self, installed=True, enabled=True):
        self.installed, self.enabled = installed, enabled
        self.calls: list[list[str]] = []
        self.created_xml = None

    def __call__(self, args):
        self.calls.append(args)
        op = args[1]
        if op == "/Query":
            if not self.installed:
                return subprocess.CompletedProcess(args, 1, "", "ERRO: não encontrado")
            out = QUERY_XML.format(enabled=str(self.enabled).lower())
            return subprocess.CompletedProcess(args, 0, out, "")
        if op == "/Create":
            self.created_xml = Path(args[args.index("/XML") + 1]).read_text(encoding="utf-16")
            self.installed = True
        if op == "/Change":
            self.enabled = args[-1] == "/ENABLE"
        if op == "/Delete":
            self.installed = False
        return subprocess.CompletedProcess(args, 0, "SUCESSO", "")


def test_task_xml_has_workdir_wake_and_catch_up():
    xml = build_task_xml(
        Path(r"C:\Projetos\night shift\.venv\Scripts\night-shift.exe"),
        "run",
        Path(r"C:\Projetos\night shift"),
        time(2, 0),
        max_hours=3,
    )
    assert "T02:00:00</StartBoundary>" in xml
    assert r"<WorkingDirectory>C:\Projetos\night shift</WorkingDirectory>" in xml
    assert "<Arguments>run</Arguments>" in xml
    assert "<WakeToRun>true</WakeToRun>" in xml
    assert "<StartWhenAvailable>true</StartWhenAvailable>" in xml
    assert "<DisallowStartIfOnBatteries>false</DisallowStartIfOnBatteries>" in xml
    assert "<ExecutionTimeLimit>PT3H</ExecutionTimeLimit>" in xml
    assert "<LogonType>InteractiveToken</LogonType>" in xml, "sem senha, sem admin"
    assert "<MultipleInstancesPolicy>IgnoreNew</MultipleInstancesPolicy>" in xml


def test_install_writes_utf16_xml_and_forces_replace(tmp_path):
    fake = FakeSchtasks(installed=False)
    WindowsTaskScheduler(runner=fake).install(
        tmp_path / "night-shift.exe", "run", tmp_path, time(3, 15)
    )
    create = next(c for c in fake.calls if c[1] == "/Create")
    assert create[:4] == ["schtasks.exe", "/Create", "/TN", r"\NightShift\Nightly"]
    assert create[-1] == "/F"
    assert "T03:15:00" in fake.created_xml


def test_status_reads_settings_enabled_and_time():
    on = WindowsTaskScheduler(runner=FakeSchtasks(enabled=True)).status()
    off = WindowsTaskScheduler(runner=FakeSchtasks(enabled=False)).status()
    missing = WindowsTaskScheduler(runner=FakeSchtasks(installed=False)).status()

    assert on == ScheduleStatus(installed=True, enabled=True, at=time(2, 30))
    assert off.enabled is False
    assert on.describe() == "todo dia às 02:30"
    assert off.describe() == "todo dia às 02:30 (desligado)"
    assert missing.describe() == "não agendado"


def test_enable_disable_remove_only_when_installed():
    fake = FakeSchtasks()
    sched = WindowsTaskScheduler(runner=fake)
    assert sched.disable() and fake.enabled is False
    assert sched.enable() and fake.enabled is True
    assert sched.remove() and fake.installed is False

    for op in (sched.enable, sched.disable, sched.remove):
        assert op() is False
