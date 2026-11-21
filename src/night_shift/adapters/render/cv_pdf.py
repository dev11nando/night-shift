"""CV ajustado → PDF de uma coluna, sóbrio e legível por ATS (texto selecionável, sem
tabelas nem imagens)."""

import re
from pathlib import Path

from fpdf import FPDF

from night_shift.domain.cv import TailoredCV

FONT_DIR = Path("C:/Windows/Fonts")
MONTHS = ["Jan", "Fev", "Mar", "Abr", "Mai", "Jun", "Jul", "Ago", "Set", "Out", "Nov", "Dez"]

INK = (28, 28, 26)
MUTED = (95, 95, 90)
RULE = (200, 200, 195)


def format_period(period: str | None) -> str:
    """``2024-02/2026-08`` → ``Fev/2024 – Ago/2026``; o que não casar fica como está."""
    if not period:
        return ""

    def month(part: str) -> str:
        m = re.fullmatch(r"(\d{4})-(\d{2})", part.strip())
        return f"{MONTHS[int(m.group(2)) - 1]}/{m.group(1)}" if m else part.strip()

    return " – ".join(month(p) for p in period.split("/"))


class _Doc(FPDF):
    def __init__(self) -> None:
        super().__init__(format="A4")
        self.set_margins(18, 16, 18)
        self.set_auto_page_break(True, margin=16)
        regular, bold = FONT_DIR / "arial.ttf", FONT_DIR / "arialbd.ttf"
        if regular.exists() and bold.exists():
            self.add_font("Body", "", str(regular))
            self.add_font("Body", "B", str(bold))
            self._body_font = "Body"
            self._unicode_ok = True
        else:  # fonte embutida só cobre latin-1: suficiente para português
            self._body_font = "Helvetica"
            self._unicode_ok = False

    def text_safe(self, text: str) -> str:
        if self._unicode_ok:
            return text
        swaps = {"–": "-", "—": "-", "•": "-", "“": '"', "”": '"', "’": "'"}
        for a, b in swaps.items():
            text = text.replace(a, b)
        return text.encode("latin-1", "replace").decode("latin-1")

    def font(self, size: float, bold: bool = False, color=INK) -> None:
        self.set_font(self._body_font, "B" if bold else "", size)
        self.set_text_color(*color)

    def section(self, title: str) -> None:
        self.ln(3)
        self.font(10.5, bold=True)
        self.cell(0, 6, self.text_safe(title.upper()), new_x="LMARGIN", new_y="NEXT")
        self.set_draw_color(*RULE)
        self.line(self.l_margin, self.get_y(), self.w - self.r_margin, self.get_y())
        self.ln(2)

    def paragraph(self, text: str, size: float = 9.5, color=INK) -> None:
        self.font(size, color=color)
        self.multi_cell(0, 4.6, self.text_safe(text), new_x="LMARGIN", new_y="NEXT")

    def bullet(self, text: str) -> None:
        self.font(9.5)
        indent = 4
        self.set_x(self.l_margin)
        self.cell(indent, 4.6, self.text_safe("•"))
        self.multi_cell(0, 4.6, self.text_safe(text), new_x="LMARGIN", new_y="NEXT")
        self.ln(0.6)


def render_cv_pdf(cv: TailoredCV, name: str, email: str, out: Path) -> Path:
    m = cv.master
    doc = _Doc()
    doc.add_page()

    doc.font(18, bold=True)
    doc.cell(0, 9, doc.text_safe(name.upper()), new_x="LMARGIN", new_y="NEXT")
    if m.headline:
        doc.font(11, color=MUTED)
        doc.cell(0, 6, doc.text_safe(m.headline), new_x="LMARGIN", new_y="NEXT")
    contact = [email, m.contact.phone, m.contact.location, m.contact.linkedin, m.contact.github]
    doc.font(9, color=MUTED)
    doc.cell(
        0, 5, doc.text_safe("  ·  ".join(c for c in contact if c)), new_x="LMARGIN", new_y="NEXT"
    )

    doc.section("Resumo")
    doc.paragraph(cv.summary)

    doc.section("Experiência")
    for i, exp in enumerate(cv.experiences):
        if i:
            doc.ln(2)
        doc.font(10.5, bold=True)
        doc.cell(
            0, 5.5, doc.text_safe(f"{exp.role} · {exp.company}"), new_x="LMARGIN", new_y="NEXT"
        )
        doc.font(9, color=MUTED)
        doc.cell(0, 4.6, doc.text_safe(format_period(exp.period)), new_x="LMARGIN", new_y="NEXT")
        doc.ln(1)
        for b in exp.bullets:
            doc.bullet(b.text)

    if cv.skills:
        doc.section("Habilidades")
        doc.paragraph(", ".join(cv.skills))

    if m.education:
        doc.section("Formação")
        for ed in m.education:
            period = format_period(ed.period)
            doc.paragraph(f"{ed.course} — {ed.school}" + (f" ({period})" if period else ""))

    if m.courses:
        doc.section("Cursos")
        doc.paragraph(", ".join(m.courses))

    if m.languages:
        doc.section("Idiomas")
        doc.paragraph(", ".join(f"{la.name} ({la.level})" for la in m.languages))

    out.parent.mkdir(parents=True, exist_ok=True)
    doc.output(str(out))
    return out
