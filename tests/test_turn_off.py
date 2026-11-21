"""Turn-off com processos de verdade: um que obedece o STOP e um que ignora."""

import subprocess
import sys
import textwrap
from datetime import datetime

import psutil
import pytest

from night_shift.runtime.lifecycle import running_pipeline
from night_shift.runtime.logs import open_run_log, prune, tee
from night_shift.runtime.pids import PidRegistry, kill_tree
from night_shift.runtime.stop_flag import StopFlag
from night_shift.runtime.turn_off import turn_off, turn_on


class FakeScheduler:
    def __init__(self, installed=True):
        self.installed, self.enabled = installed, True

    def enable(self):
        if self.installed:
            self.enabled = True
        return self.installed

    def disable(self):
        if self.installed:
            self.enabled = False
        return self.installed


def spawn(code: str) -> subprocess.Popen:
    return subprocess.Popen([sys.executable, "-c", textwrap.dedent(code)])


@pytest.fixture
def procs():
    started: list[subprocess.Popen] = []
    yield started
    for p in started:
        kill_tree(p.pid)


def test_off_waits_for_cooperative_stop_then_kills_the_rest(paths, procs):
    stop_file = StopFlag(paths.run_dir).path
    obedient = spawn(
        f"""
        import os, time
        while not os.path.exists({str(stop_file)!r}):
            time.sleep(0.1)
        """
    )
    stubborn = spawn("import time; time.sleep(120)")
    procs += [obedient, stubborn]
    registry = PidRegistry(paths.run_dir)
    registry.register("run", pid=obedient.pid)
    registry.register("serve", pid=stubborn.pid)
    scheduler = FakeScheduler()

    report = turn_off(paths, scheduler, grace_seconds=3)

    assert report.stopped_gracefully == [f"run (PID {obedient.pid})"]
    assert report.killed == [f"serve (PID {stubborn.pid})"]
    assert report.survivors == []
    assert not psutil.pid_exists(stubborn.pid) or psutil.Process(stubborn.pid).status() == "zombie"
    assert report.task_disabled and scheduler.enabled is False
    assert StopFlag(paths.run_dir).is_set()
    assert "tarefa agendada desligada" in report.lines()


def test_off_with_nothing_running(paths):
    report = turn_off(paths, FakeScheduler(installed=False), grace_seconds=1)
    assert report.lines()[:2] == [
        "nenhum processo do night-shift estava rodando",
        "nenhuma tarefa agendada",
    ]


def test_off_never_kills_itself(paths):
    PidRegistry(paths.run_dir).register("serve")  # o próprio processo do teste
    report = turn_off(paths, None, grace_seconds=0)
    assert report.killed == []


def test_on_clears_stop_and_enables_task(paths):
    scheduler = FakeScheduler()
    scheduler.enabled = False
    StopFlag(paths.run_dir).request()

    assert turn_on(paths, scheduler) is True
    assert scheduler.enabled and not StopFlag(paths.run_dir).is_set()


def test_running_pipeline_ignores_panel_and_self(paths, procs):
    registry = PidRegistry(paths.run_dir)
    registry.register("run")  # este processo
    panel = spawn("import time; time.sleep(120)")
    procs.append(panel)
    registry.register("serve", pid=panel.pid)
    assert running_pipeline(paths) is None

    other = spawn("import time; time.sleep(120)")
    procs.append(other)
    registry.register("rank", pid=other.pid)
    assert running_pipeline(paths).name == "rank"


def test_run_log_tee_and_prune(tmp_path):
    echoed = []
    with open_run_log(tmp_path, "run", now=datetime(2026, 11, 22, 2, 0, 0)) as f:
        tee(echoed.append, f)("coleta")
    [log] = tmp_path.glob("*.log")
    assert log.name == "20261122-020000-run.log"
    assert log.read_text(encoding="utf-8").strip().endswith("coleta")
    assert echoed == ["coleta"]

    for i in range(5):
        (tmp_path / f"2026010{i}-000000-run.log").write_text("x")
    prune(tmp_path, keep=2)
    assert len(list(tmp_path.glob("*.log"))) == 2
    assert (tmp_path / "20261122-020000-run.log").exists(), "mantém os mais recentes"
