from pathlib import Path

import pytest

from night_shift.paths import HOME_ENV, ProjectPaths


@pytest.fixture
def paths(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> ProjectPaths:
    """Raiz isolada e vazia; os *.example.yaml continuam vindo do repo."""
    monkeypatch.setenv(HOME_ENV, str(tmp_path))
    p = ProjectPaths.from_env()
    p.ensure_dirs()
    return p
