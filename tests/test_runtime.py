import subprocess
import sys
import textwrap

import psutil
import pytest

from night_shift.runtime.job_object import IS_WINDOWS
from night_shift.runtime.pids import PidRegistry, kill_tree
from night_shift.runtime.stop_flag import StopFlag

SLEEPER = [sys.executable, "-c", "import time; time.sleep(120)"]


def _wait_dead(pid: int, timeout: float = 10) -> bool:
    try:
        psutil.Process(pid).wait(timeout=timeout)
    except psutil.NoSuchProcess:
        pass
    except psutil.TimeoutExpired:
        return False
    return True


def _spawn_parent_with_grandchild(prelude: str = "") -> tuple[subprocess.Popen, int, int]:
    """Sobe um processo que cria um neto e imprime "<pid_do_interpretador> <pid_do_neto>".

    No Windows o python.exe da venv é um launcher que abre o interpretador real como
    filho, por isso o próprio script informa o PID que importa.
    """
    code = textwrap.dedent(
        f"""
        import os, subprocess, sys, time
        {prelude}
        gc = subprocess.Popen({SLEEPER!r})
        print(os.getpid(), gc.pid, flush=True)
        time.sleep(120)
        """
    )
    proc = subprocess.Popen([sys.executable, "-c", code], stdout=subprocess.PIPE, text=True)
    interp_pid, grandchild_pid = map(int, proc.stdout.readline().split())
    return proc, interp_pid, grandchild_pid


def test_stop_flag(tmp_path):
    flag = StopFlag(tmp_path / "run")
    assert not flag.is_set()
    flag.request()
    assert flag.is_set()
    flag.clear()
    assert not flag.is_set()
    flag.clear()  # idempotente


def test_pid_registry_tracks_only_live_processes(tmp_path):
    reg = PidRegistry(tmp_path)
    proc = subprocess.Popen(SLEEPER)
    try:
        reg.register("pytest")
        reg.register("sleeper", pid=proc.pid)
        assert {e.name for e in reg.alive()} == {"pytest", "sleeper"}

        proc.kill()
        proc.wait()
        assert {e.name for e in reg.alive()} == {"pytest"}

        reg.unregister()
        assert reg.alive() == []
    finally:
        proc.kill()


def test_kill_tree_takes_grandchildren(tmp_path):
    proc, _, grandchild = _spawn_parent_with_grandchild()
    try:
        assert psutil.pid_exists(grandchild)
        assert kill_tree(proc.pid) == []
        assert _wait_dead(grandchild)
    finally:
        kill_tree(proc.pid)
        kill_tree(grandchild)


@pytest.mark.skipif(not IS_WINDOWS, reason="Job Object só existe no Windows")
def test_job_object_kills_children_when_owner_dies():
    prelude = (
        "from night_shift.runtime.job_object import JobObject; "
        "job = JobObject(); assert job.adopt_current_process()"
    )
    proc, interp, grandchild = _spawn_parent_with_grandchild(prelude)
    try:
        assert psutil.pid_exists(grandchild)
        # Morte abrupta do dono do job (sem atexit, sem cleanup): o neto tem que morrer junto.
        psutil.Process(interp).kill()
        assert _wait_dead(grandchild), "neto sobreviveu: Job Object não matou a árvore"
    finally:
        kill_tree(proc.pid)
        kill_tree(grandchild)  # se o teste falhou, o neto virou órfão e não está mais na árvore
