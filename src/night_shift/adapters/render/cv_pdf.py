"""CV ajustado → PDF de uma coluna, sóbrio e legível por ATS (texto selecionável, sem
tabelas nem imagens), que **sempre cabe em uma página**.

Se o conteúdo passar de uma página, o render tenta de novo com fonte e espaçamento um
pouco menores (até 82%); se ainda não couber, tira a seção de cursos e, por último, os
bullets do fim (menos relevantes) da experiência mais longa, mantendo pelo menos 2.
"""

import re
from dataclasses import dataclass, replace
from pathlib import Path

from fpdf import FPDF

from night_shift.domain.cv import TailoredCV

FONT_DIR = Path("C:/Windows/Fonts")
MONTHS = {
    "pt": ["Jan", "Fev", "Mar", "Abr", "Mai", "Jun", "Jul", "Ago", "Set", "Out", "Nov", "Dez"],
    "en": ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"],
}
LABELS = {
    "pt": {
        "summary": "Resumo",
        "experience": "Experiência",
        "projects": "Projetos",
        "skills": "Habilidades",
        "education": "Formação",
        "courses": "Cursos",
        "languages": "Idiomas",
    },
    "en": {
        "summary": "Summary",
        "experience": "Experience",
        "projects": "Projects",
        "skills": "Skills",
        "education": "Education",
        "courses": "Courses",
        "languages": "Languages",
    },
}
SCALES = (1.0, 0.96, 0.92, 0.88, 0.85, 0.82)
MIN_BULLETS = 2

INK = (28, 28, 26)
MUTED = (95, 95, 90)
RULE = (200, 200, 195)


def format_period(period: str | None, lang: str = "pt") -> str:
    """``2024-02/2026-08`` → ``Fev/2024 – Ago/2026``; o que não casar fica como está."""
    if not period:
        return ""

    def month(part: str) -> str:
        m = re.fullmatch(r"(\d{4})-(\d{2})", part.strip())
        if not m:
            return part.strip()
        name = MONTHS[lang][int(m.group(2)) - 1]
        return f"{name} {m.group(1)}" if lang == "en" else f"{name}/{m.group(1)}"

    return " – ".join(month(p) for p in period.split("/"))


class _Doc(FPDF):
    def __init__(self, scale: float = 1.0) -> None:
        super().__init__(format="A4")
        self.k_scale = scale
        margin = 18 if scale >= 0.9 else 15
        self.set_margins(margin, 14 * max(scale, 0.85), margin)
        self.set_auto_page_break(True, margin=12)
        regular, bold = FONT_DIR / "arial.ttf", FONT_DIR / "arialbd.ttf"
        if regular.exists() and bold.exists():
            self.add_font("Body", "", str(regular))
            self.add_font("Body", "B", str(bold))
            self._body_font = "Body"
            self._unicode_ok = True
        else:  # fonte embutida só cobre latin-1: suficiente para português
            self._body_font = "Helvetica"
            self._unicode_ok = False

    def s(self, value: float) -> float:
        return value * self.k_scale

    def text_safe(self, text: str) -> str:
        if self._unicode_ok:
            return text
        swaps = {"–": "-", "—": "-", "•": "-", "“": '"', "”": '"', "’": "'"}
        for a, b in swaps.items():
            text = text.replace(a, b)
        return text.encode("latin-1", "replace").decode("latin-1")

    def font(self, size: float, bold: bool = False, color=INK) -> None:
        self.set_font(self._body_font, "B" if bold else "", self.s(size))
        self.set_text_color(*color)

    def line_cell(self, size: float, text: str, height: float, bold=False, color=INK) -> None:
        self.font(size, bold, color)
        self.cell(0, self.s(height), self.text_safe(text), new_x="LMARGIN", new_y="NEXT")

    def section(self, title: str) -> None:
        self.ln(self.s(3))
        self.line_cell(10.5, title.upper(), 6, bold=True)
        self.set_draw_color(*RULE)
        self.line(self.l_margin, self.get_y(), self.w - self.r_margin, self.get_y())
        self.ln(self.s(2))

    def paragraph(self, text: str, size: float = 9.5, color=INK) -> None:
        self.font(size, color=color)
        self.multi_cell(0, self.s(4.6), self.text_safe(text), new_x="LMARGIN", new_y="NEXT")

    def bullet(self, text: str) -> None:
        self.font(9.5)
        self.set_x(self.l_margin)
        self.cell(self.s(4), self.s(4.6), self.text_safe("•"))
        self.multi_cell(0, self.s(4.6), self.text_safe(text), new_x="LMARGIN", new_y="NEXT")
        self.ln(self.s(0.6))

    def block(self, title: str, subtitle: str, bullets) -> None:
        """Experiência ou projeto: título, linha cinza (período/contexto) e bullets."""
        self.line_cell(10.5, title, 5.5, bold=True)
        if subtitle:
            self.line_cell(9, subtitle, 4.6, color=MUTED)
        self.ln(self.s(1))
        for b in bullets:
            self.bullet(b.text)


@dataclass(frozen=True)
class RenderInfo:
    path: Path
    scale: float
    dropped_courses: bool
    trimmed_bullets: int


def _build(cv: TailoredCV, name: str, email: str, lang: str, scale: float, courses: bool):
    t = LABELS[lang]
    m = cv.master
    doc = _Doc(scale)
    doc.add_page()

    doc.line_cell(18, name.upper(), 9, bold=True)
    if m.headline:
        doc.line_cell(11, m.headline, 6, color=MUTED)
    contact = [email, m.contact.phone, m.contact.location, m.contact.linkedin, m.contact.github]
    doc.line_cell(9, "  ·  ".join(c for c in contact if c), 5, color=MUTED)

    doc.section(t["summary"])
    doc.paragraph(cv.summary)

    doc.section(t["experience"])
    for i, exp in enumerate(cv.experiences):
        if i:
            doc.ln(doc.s(2))
        doc.block(f"{exp.role} · {exp.company}", format_period(exp.period, lang), exp.bullets)

    if m.projects:
        doc.section(t["projects"])
        for i, proj in enumerate(m.projects):
            if i:
                doc.ln(doc.s(2))
            sub = " · ".join(x for x in (proj.context, format_period(proj.period, lang)) if x)
            doc.block(proj.name, sub, proj.bullets)

    if cv.skills:
        doc.section(t["skills"])
        doc.paragraph(", ".join(cv.skills))

    if m.education:
        doc.section(t["education"])
        for ed in m.education:
            period = format_period(ed.period, lang)
            doc.paragraph(f"{ed.course} — {ed.school}" + (f" ({period})" if period else ""))

    if courses and m.courses:
        doc.section(t["courses"])
        doc.paragraph(", ".join(m.courses))

    if m.languages:
        doc.section(t["languages"])
        doc.paragraph(", ".join(f"{la.name} ({la.level})" for la in m.languages))
    return doc


def _trim_one(cv: TailoredCV) -> TailoredCV | None:
    """Tira o último bullet da experiência com mais bullets (respeitando o mínimo)."""
    longest = max(range(len(cv.experiences)), key=lambda i: len(cv.experiences[i].bullets))
    exp = cv.experiences[longest]
    if len(exp.bullets) <= MIN_BULLETS:
        return None
    exps = list(cv.experiences)
    exps[longest] = exp.model_copy(update={"bullets": exp.bullets[:-1]})
    return replace(cv, experiences=exps)


def render_cv_pdf_info(
    cv: TailoredCV, name: str, email: str, out: Path, lang: str = "pt"
) -> RenderInfo:
    out.parent.mkdir(parents=True, exist_ok=True)
    attempts = [(scale, True) for scale in SCALES] + [(SCALES[-1], False)]
    for scale, courses in attempts:
        doc = _build(cv, name, email, lang, scale, courses)
        if doc.page_no() == 1:
            doc.output(str(out))
            return RenderInfo(out, scale, not courses, 0)
    trimmed = 0
    while (smaller := _trim_one(cv)) is not None:
        cv, trimmed = smaller, trimmed + 1
        doc = _build(cv, name, email, lang, SCALES[-1], False)
        if doc.page_no() == 1:
            break
    doc.output(str(out))  # se nem assim couber, sai como está (o aviso fica no RenderInfo)
    return RenderInfo(out, SCALES[-1], True, trimmed)


def render_cv_pdf(cv: TailoredCV, name: str, email: str, out: Path, lang: str = "pt") -> Path:
    return render_cv_pdf_info(cv, name, email, out, lang).path


def page_count(path: Path) -> int:
    """Páginas de um PDF gerado aqui (conta os objetos /Type /Page)."""
    return len(re.findall(rb"/Type\s*/Page\b", path.read_bytes()))
