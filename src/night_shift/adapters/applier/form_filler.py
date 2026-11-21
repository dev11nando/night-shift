"""Preenche um formulário de candidatura aberto no Playwright. Nunca clica em enviar.

Funciona por rótulo (não por seletor fixo de cada ATS), então serve para Greenhouse, Lever
e Ashby e resiste a mudanças pequenas de layout.
"""

from dataclasses import dataclass, field
from pathlib import Path

from playwright.sync_api import Locator, Page

from night_shift.config import FixedAnswer
from night_shift.domain.form_fields import Field, classify

CAPTCHA_FRAMES = ("recaptcha", "hcaptcha", "challenges.cloudflare.com", "turnstile")


@dataclass(frozen=True)
class Candidate:
    """O que o sistema pode preencher sozinho."""

    first_name: str
    last_name: str
    email: str
    phone: str | None
    location: str | None
    linkedin: str | None
    github: str | None
    current_company: str | None
    resume_pdf: Path
    cover_letter: str | None
    answers: list[FixedAnswer] = field(default_factory=list)

    @property
    def full_name(self) -> str:
        return f"{self.first_name} {self.last_name}".strip()

    def value_for(self, f: Field) -> str | None:
        return {
            Field.FIRST_NAME: self.first_name,
            Field.LAST_NAME: self.last_name,
            Field.FULL_NAME: self.full_name,
            Field.EMAIL: self.email,
            Field.PHONE: self.phone,
            Field.LOCATION: self.location,
            Field.LINKEDIN: self.linkedin,
            Field.GITHUB: self.github,
            Field.CURRENT_COMPANY: self.current_company,
            Field.COVER_LETTER: self.cover_letter,
        }.get(f)


@dataclass
class FillReport:
    filled: list[str] = field(default_factory=list)
    sensitive_skipped: list[str] = field(default_factory=list)
    unanswered_required: list[str] = field(default_factory=list)
    resume_attached: bool = False
    captcha: str | None = None

    def as_dict(self) -> dict:
        return {
            "filled": self.filled,
            "sensitive_skipped": self.sensitive_skipped,
            "unanswered_required": self.unanswered_required,
            "resume_attached": self.resume_attached,
            "captcha": self.captcha,
        }


# Lê rótulo, tipo e obrigatoriedade de cada campo visível de uma vez só.
_FIELDS_JS = """() => {
  const visible = el => !!(el.offsetWidth || el.offsetHeight || el.getClientRects().length);
  const labelOf = el => {
    if (el.labels && el.labels.length) return el.labels[0].innerText;
    const by = el.getAttribute('aria-labelledby');
    if (by) return by.split(' ').map(id => document.getElementById(id)?.innerText || '').join(' ');
    return el.getAttribute('aria-label') || el.placeholder || '';
  };
  return [...document.querySelectorAll('input, textarea, select')].map((el, i) => {
    el.setAttribute('data-ns-idx', i);
    return {
      idx: i,
      tag: el.tagName.toLowerCase(),
      type: (el.type || '').toLowerCase(),
      name: el.name || '',
      id: el.id || '',
      label: (labelOf(el) || '').replace(/\\s+/g, ' ').trim(),
      required: el.required || el.getAttribute('aria-required') === 'true',
      visible: visible(el) || el.type === 'file',
      empty: el.type === 'checkbox' || el.type === 'radio' ? null : !el.value,
    };
  });
}"""

# Obrigatório = atributo required/aria-required OU rótulo terminado em * / ✱: muitos
# formulários em React (ex.: Greenhouse do BTG) só marcam com o asterisco visual.
_UNANSWERED_JS = """() => {
  const visible = el => !!(el.offsetWidth || el.offsetHeight || el.getClientRects().length);
  const labelOf = el => {
    if (el.labels && el.labels.length) return el.labels[0].innerText;
    const by = el.getAttribute('aria-labelledby');
    if (by) return by.split(' ').map(id => document.getElementById(id)?.innerText || '').join(' ');
    return el.getAttribute('aria-label') || el.placeholder || el.name || el.id || '';
  };
  const out = [];
  const seenRadio = new Set();
  for (const el of document.querySelectorAll('input, textarea, select')) {
    if (el.type === 'hidden' || (el.type !== 'file' && !visible(el))) continue;
    const label = (labelOf(el) || '').replace(/\\s+/g, ' ').trim();
    const req = el.required || el.getAttribute('aria-required') === 'true'
      || /[*✱]\\s*$/.test(label);
    if (!req) continue;
    if (el.type === 'radio') {
      if (seenRadio.has(el.name)) continue;
      seenRadio.add(el.name);
      if (!document.querySelector(`input[name="${CSS.escape(el.name)}"]:checked`)) out.push(label);
    } else if (el.type === 'checkbox') {
      if (!el.checked) out.push(label);
    } else if (el.type === 'file') {
      if (!el.files || !el.files.length) out.push(label);
    } else if (!el.value) {
      out.push(label);
    }
  }
  return out;
}"""


def detect_captcha(page: Page) -> str | None:
    for frame in page.frames:
        url = frame.url.lower()
        for marker in CAPTCHA_FRAMES:
            if marker in url:
                return marker
    return None


def _control(page: Page, idx: int) -> Locator:
    return page.locator(f'[data-ns-idx="{idx}"]')


def fill_form(page: Page, cand: Candidate) -> FillReport:
    report = FillReport()
    fields = page.evaluate(_FIELDS_JS)
    has_last_name = any(
        classify(f["label"], [], False).field is Field.LAST_NAME for f in fields if f["visible"]
    )
    resume_target = None

    for f in fields:
        if not f["visible"] or f["type"] in ("hidden", "submit", "button", "checkbox", "radio"):
            continue
        label = f["label"] or f["name"] or f["id"]
        c = classify(label, cand.answers, has_last_name)
        if c.sensitive:
            report.sensitive_skipped.append(label)
            continue

        if f["type"] == "file":
            hint = f"{label} {f['name']} {f['id']}"
            is_resume = classify(hint, [], False).field is Field.RESUME
            if is_resume and resume_target is None:
                resume_target = f["idx"]
            continue
        if f["tag"] == "select":
            continue  # opções variam demais; fica para você

        value = c.answer if c.answer is not None else (cand.value_for(c.field) if c.field else None)
        if not value or not f["empty"]:
            continue
        control = _control(page, f["idx"])
        try:
            control.fill(value, timeout=3000)
        except Exception:
            continue
        report.filled.append(label)

    # Formulário sem rótulo claro de currículo: usa o primeiro upload.
    if resume_target is None:
        uploads = [f for f in fields if f["type"] == "file"]
        resume_target = uploads[0]["idx"] if uploads else None
    if resume_target is not None and cand.resume_pdf.exists():
        try:
            _control(page, resume_target).set_input_files(str(cand.resume_pdf), timeout=5000)
            report.resume_attached = True
        except Exception:
            pass

    report.captcha = detect_captcha(page)
    report.unanswered_required = [
        label for label in page.evaluate(_UNANSWERED_JS) if label not in report.filled
    ]
    return report
