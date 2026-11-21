import os
from dataclasses import dataclass
from pathlib import Path

HOME_ENV = "NIGHT_SHIFT_HOME"


@dataclass(frozen=True)
class ProjectPaths:
    """Onde o night-shift guarda config, banco e arquivos de runtime.

    A raiz vem de ``NIGHT_SHIFT_HOME`` ou, se não definida, do diretório atual.
    """

    root: Path

    @classmethod
    def from_env(cls) -> "ProjectPaths":
        return cls(Path(os.environ.get(HOME_ENV) or Path.cwd()).resolve())

    @property
    def config_dir(self) -> Path:
        return self.root / "config"

    @property
    def data_dir(self) -> Path:
        return self.root / "data"

    @property
    def run_dir(self) -> Path:
        """Arquivos efêmeros de controle: PIDs, flag de STOP."""
        return self.root / "run"

    @property
    def db_path(self) -> Path:
        return self.data_dir / "night-shift.db"

    @property
    def db_url(self) -> str:
        return f"sqlite:///{self.db_path.as_posix()}"

    @property
    def profile_file(self) -> Path:
        return self.config_dir / "profile.yaml"

    def ensure_dirs(self) -> None:
        for d in (self.config_dir, self.data_dir, self.run_dir):
            d.mkdir(parents=True, exist_ok=True)
