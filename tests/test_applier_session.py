"""Sessão assistida completa (Playwright próprio; não pode dividir processo com o
navegador compartilhado de test_applier.py)."""

import pytest

import tests.test_applier as fixtures
from night_shift.adapters.applier.assisted import AssistedApplier
from tests.test_applier import GREENHOUSE_LIKE

resume = pytest.fixture(fixtures.resume.__wrapped__)
cand = pytest.fixture(fixtures.cand.__wrapped__)


def test_assisted_preview_and_confirmation(tmp_path, cand):
    form = tmp_path / "form.html"
    form.write_text(
        GREENHOUSE_LIKE.replace(
            "</body>",
            "<script>if (location.hash === '#auto') document.getElementById('resume')"
            ".addEventListener('change', () => setTimeout(() => document.body.innerHTML ="
            " '<h1>Thank you for applying!</h1>', 500))</script></body>",
        ),
        encoding="utf-8",
    )
    shots = tmp_path / "shots"
    with AssistedApplier(tmp_path / "profile", shots, headless=True, wait_minutes=0.2) as ap:
        preview = ap.apply(7, form.as_uri(), cand, preview=True)
        # "#auto" simula você enviando logo depois que o CV foi anexado.
        applied = ap.apply(8, form.as_uri() + "#auto", cand, preview=False)

    assert preview.status == "preview"
    assert preview.filled_shot == shots / "7-preenchido.png" and preview.filled_shot.exists()
    assert applied.status == "applied"
    assert applied.confirmed_shot.exists()
    assert applied.as_dict()["resume_attached"] is True
