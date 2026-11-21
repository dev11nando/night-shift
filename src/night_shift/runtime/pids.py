import contextlib
import json
import os
from dataclasses import asdict, dataclass
from pathlib import Path

import psutil


@dataclass(frozen=True)
class PidEntry:
    pid: int
    name: str
    create_time: float  # distingue o nosso processo de outro que reusou o mesmo PID


class PidRegistry:
    """Registro em ``run/pids.json`` dos processos-raiz do night-shift.

    É a rede de segurança do ``off``: mesmo que o Job Object falhe, os PIDs daqui
    são mortos com a árvore inteira.
    """

    def __init__(self, run_dir: Path) -> None:
        self.path = run_dir / "pids.json"

    def _read(self) -> list[PidEntry]:
        try:
            raw = json.loads(self.path.read_text(encoding="utf-8"))
        except (FileNotFoundError, json.JSONDecodeError):
            return []
        return [PidEntry(**e) for e in raw]

    def _write(self, entries: list[PidEntry]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_suffix(".tmp")
        tmp.write_text(json.dumps([asdict(e) for e in entries], indent=2), encoding="utf-8")
        os.replace(tmp, self.path)

    def register(self, name: str, pid: int | None = None) -> PidEntry:
        pid = pid or os.getpid()
        entry = PidEntry(pid=pid, name=name, create_time=psutil.Process(pid).create_time())
        self._write([e for e in self.alive() if e.pid != pid] + [entry])
        return entry

    def unregister(self, pid: int | None = None) -> None:
        pid = pid or os.getpid()
        self._write([e for e in self._read() if e.pid != pid])

    def alive(self) -> list[PidEntry]:
        """Entradas cujo processo ainda existe e é o mesmo (mesmo create_time)."""
        return [e for e in self._read() if _is_same_process(e)]


def _is_same_process(entry: PidEntry) -> bool:
    try:
        return psutil.Process(entry.pid).create_time() == entry.create_time
    except psutil.Error:
        return False


def kill_tree(pid: int, timeout: float = 5.0) -> list[int]:
    """Mata ``pid`` e todos os descendentes. Retorna os PIDs que sobreviveram."""
    try:
        root = psutil.Process(pid)
        procs = [*root.children(recursive=True), root]
    except psutil.NoSuchProcess:
        # A raiz morreu (ou morreu durante a varredura); filhos já órfãos não são mais
        # alcançáveis por aqui. É exatamente o caso que o Job Object cobre.
        return []
    for p in procs:
        with contextlib.suppress(psutil.NoSuchProcess):
            p.kill()
    _, alive = psutil.wait_procs(procs, timeout=timeout)
    return [p.pid for p in alive]
