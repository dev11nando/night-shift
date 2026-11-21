"""Aplicação assistida: o sistema abre e preenche, você confere e envia.

Um navegador visível com perfil próprio em ``data/browser-profile`` (logins e cookies
ficam entre execuções). Para cada vaga: abre o formulário, preenche o que é seguro, tira
um print, mostra um aviso na página e espera. Você completa, resolve o captcha se
aparecer e envia; o sistema reconhece a tela de confirmação e tira outro print. Fechar a
aba pula a vaga.
"""

import contextlib
import re
import time
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from playwright.sync_api import BrowserContext, Page, sync_playwright

from night_shift.adapters.applier.form_filler import Candidate, FillReport, fill_form
from night_shift.domain.enums import Source
from night_shift.domain.form_fields import is_confirmation

Status = Literal["applied", "skipped", "timeout", "preview", "error"]

_CONFIRMATION_URL = re.compile(r"confirm|thank|obrigad|success|sucesso", re.IGNORECASE)

_BANNER_JS = """(msg) => {
  const box = document.createElement('div');
  box.id = 'night-shift-banner';
  box.textContent = msg;
  Object.assign(box.style, {
    position: 'fixed', right: '16px', bottom: '16px', zIndex: 2147483647, maxWidth: '360px',
    padding: '12px 14px', borderRadius: '10px', background: '#1c1c1a', color: '#fff',
    font: '14px/1.4 system-ui, sans-serif', boxShadow: '0 4px 16px rgba(0,0,0,.3)'
  });
  document.body.appendChild(box);
}"""


def apply_url(source: Source, slug: str | None, external_id: str) -> str | None:
    """Página do formulário no próprio ATS (não na página de carreiras da empresa, que às
    vezes embute o formulário num iframe)."""
    if not slug:
        return None
    return {
        Source.GREENHOUSE: f"https://job-boards.greenhouse.io/{slug}/jobs/{external_id}",
        Source.LEVER: f"https://jobs.lever.co/{slug}/{external_id}/apply",
        Source.ASHBY: f"https://jobs.ashbyhq.com/{slug}/{external_id}/application",
    }.get(source)


@dataclass
class ApplyOutcome:
    status: Status
    report: FillReport | None = None
    filled_shot: Path | None = None
    confirmed_shot: Path | None = None
    message: str = ""

    def as_dict(self) -> dict:
        return {
            "status": self.status,
            "message": self.message,
            "filled_shot": str(self.filled_shot) if self.filled_shot else None,
            "confirmed_shot": str(self.confirmed_shot) if self.confirmed_shot else None,
            **(self.report.as_dict() if self.report else {}),
        }


def wait_for_confirmation(
    page: Page,
    timeout_s: float,
    *,
    poll_s: float = 1.0,
    clock: Callable[[], float] = time.monotonic,
) -> Status:
    """Espera a tela de confirmação. ``skipped`` se a aba fechar, ``timeout`` se o tempo
    acabar."""
    deadline = clock() + timeout_s
    start_url = page.url
    while clock() < deadline:
        if page.is_closed():
            return "skipped"
        try:
            # URL só conta se mudou: o slug da empresa pode ter "success" no nome.
            moved = page.url != start_url and _CONFIRMATION_URL.search(page.url)
            if moved or is_confirmation(page.inner_text("body")):
                return "applied"
        except Exception:
            if page.is_closed():
                return "skipped"
        page.wait_for_timeout(poll_s * 1000)
    return "timeout"


class AssistedApplier:
    def __init__(
        self,
        profile_dir: Path,
        shots_dir: Path,
        *,
        headless: bool = False,
        wait_minutes: float = 15,
    ) -> None:
        self.profile_dir, self.shots_dir = profile_dir, shots_dir
        self.headless, self.wait_minutes = headless, wait_minutes
        self._pw = None
        self.context: BrowserContext | None = None

    def __enter__(self) -> "AssistedApplier":
        self.profile_dir.mkdir(parents=True, exist_ok=True)
        self.shots_dir.mkdir(parents=True, exist_ok=True)
        self._pw = sync_playwright().start()
        self.context = self._pw.chromium.launch_persistent_context(
            str(self.profile_dir), headless=self.headless, locale="pt-BR", viewport=None
        )
        return self

    def __exit__(self, *exc) -> None:
        if self.context is not None:
            self.context.close()
        if self._pw is not None:
            self._pw.stop()

    def open_form(self, url: str) -> Page:
        page = self.context.new_page()
        page.goto(url, wait_until="domcontentloaded", timeout=60_000)
        with contextlib.suppress(Exception):
            page.wait_for_load_state("load", timeout=20_000)
        page.wait_for_timeout(2_000)  # formulários em React (Ashby) montam depois do load
        return page

    def apply(self, job_id: int, url: str, cand: Candidate, *, preview: bool) -> ApplyOutcome:
        try:
            page = self.open_form(url)
        except Exception as e:
            return ApplyOutcome("error", message=f"não abriu o formulário: {e}")
        try:
            report = fill_form(page, cand)
            filled_shot = self.shots_dir / f"{job_id}-preenchido.png"
            page.screenshot(path=str(filled_shot), full_page=True)
            if preview:
                page.close()
                return ApplyOutcome("preview", report, filled_shot, message="só preenchido")

            pending = len(report.unanswered_required)
            page.evaluate(
                _BANNER_JS,
                "night-shift: confira o que foi preenchido"
                + (f", complete {pending} campo(s) obrigatório(s)" if pending else "")
                + " e envie. Fechar esta aba pula a vaga.",
            )
            page.bring_to_front()
            status = wait_for_confirmation(page, self.wait_minutes * 60)
            confirmed = None
            if status == "applied":
                confirmed = self.shots_dir / f"{job_id}-confirmado.png"
                page.screenshot(path=str(confirmed), full_page=True)
            if not page.is_closed():
                page.close()
            return ApplyOutcome(status, report, filled_shot, confirmed)
        except Exception as e:
            if not page.is_closed():
                page.close()
            return ApplyOutcome("error", message=str(e))
