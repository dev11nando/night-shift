"""``night-shift off`` e ``on`` (docs/ESCOPO.md §11.1).

Ordem do off: pede parada cooperativa (``run/STOP``), espera o pipeline terminar entre
etapas, mata o que sobrou (árvore inteira de cada processo registrado), descarrega o
modelo do Ollama se ele estiver em uso e desliga a tarefa agendada. O on desfaz o STOP e
religa a tarefa.
"""

import os
import shutil
import subprocess
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Protocol

import psutil

from night_shift.paths import ProjectPaths
from night_shift.runtime.pids import PidEntry, PidRegistry, kill_tree
from night_shift.runtime.stop_flag import StopFlag


class Scheduler(Protocol):
    def enable(self) -> bool: ...
    def disable(self) -> bool: ...


@dataclass
class TurnOffReport:
    stopped_gracefully: list[str] = field(default_factory=list)
    killed: list[str] = field(default_factory=list)
    survivors: list[int] = field(default_factory=list)
    task_disabled: bool = False
    ollama: str | None = None

    def lines(self) -> list[str]:
        out = []
        if not (self.stopped_gracefully or self.killed):
            out.append("nenhum processo do night-shift estava rodando")
        out += [f"parou sozinho: {p}" for p in self.stopped_gracefully]
        out += [f"encerrado à força: {p}" for p in self.killed]
        out.append("tarefa agendada desligada" if self.task_disabled else "nenhuma tarefa agendada")
        if self.ollama:
            out.append(self.ollama)
        if self.survivors:
            out.append(f"ATENÇÃO, ainda rodando (PIDs): {', '.join(map(str, self.survivors))}")
        return out


def _label(e: PidEntry) -> str:
    return f"{e.name} (PID {e.pid})"


def stop_ollama(model: str | None, kill_server: bool) -> str | None:
    """Tira o modelo da VRAM e, se pedido, encerra o servidor do Ollama."""
    exe = shutil.which("ollama")
    if exe is None:
        return None
    msgs = []
    if model:
        proc = subprocess.run([exe, "stop", model], capture_output=True, text=True, timeout=30)
        if proc.returncode == 0:
            msgs.append(f"modelo {model} descarregado da GPU")
    if kill_server:
        for p in psutil.process_iter(["name"]):
            if (p.info["name"] or "").lower().startswith("ollama"):
                kill_tree(p.pid)
                msgs.append(f"Ollama encerrado (PID {p.pid})")
    return "; ".join(msgs) or None


def turn_off(
    paths: ProjectPaths,
    scheduler: Scheduler | None,
    grace_seconds: float = 30,
    *,
    exclude_pids: frozenset[int] = frozenset(),
    ollama: Callable[[], str | None] = lambda: None,
    sleep: Callable[[float], None] = time.sleep,
    log: Callable[[str], None] = lambda _: None,
) -> TurnOffReport:
    report = TurnOffReport()
    registry = PidRegistry(paths.run_dir)
    me = os.getpid()
    targets = [e for e in registry.alive() if e.pid != me and e.pid not in exclude_pids]

    StopFlag(paths.run_dir).request()
    if targets:
        log(f"pedindo parada a {len(targets)} processo(s); espero até {grace_seconds:.0f}s")
        waited = 0.0
        while waited < grace_seconds and any(psutil.pid_exists(e.pid) for e in targets):
            sleep(0.5)
            waited += 0.5

    for e in targets:
        if not psutil.pid_exists(e.pid):
            report.stopped_gracefully.append(_label(e))
            continue
        report.survivors += kill_tree(e.pid)
        report.killed.append(_label(e))
        registry.unregister(e.pid)

    report.ollama = ollama()
    if scheduler is not None:
        report.task_disabled = scheduler.disable()
    return report


def turn_on(paths: ProjectPaths, scheduler: Scheduler | None) -> bool:
    """Tira o STOP e religa a tarefa. Retorna se havia tarefa para religar."""
    StopFlag(paths.run_dir).clear()
    return scheduler.enable() if scheduler is not None else False
