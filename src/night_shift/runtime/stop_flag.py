from pathlib import Path


class StopFlag:
    """Pedido de parada cooperativa via arquivo ``run/STOP``.

    O pipeline confere ``is_set()`` entre etapas e termina limpo; o ``off`` cria o arquivo.
    Usar arquivo (e não sinal) funciona entre processos no Windows sem console compartilhado.
    """

    def __init__(self, run_dir: Path) -> None:
        self.path = run_dir / "STOP"

    def request(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.touch()

    def is_set(self) -> bool:
        return self.path.exists()

    def clear(self) -> None:
        self.path.unlink(missing_ok=True)
