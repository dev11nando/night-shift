import re
import unicodedata

from night_shift.domain.enums import Level, WorkModel


def fold(text: str) -> str:
    """Minúsculas e sem acento: ``"Sênior"`` → ``"senior"``."""
    nfkd = unicodedata.normalize("NFKD", text.casefold())
    return "".join(c for c in nfkd if not unicodedata.combining(c))


def contains_term(text: str, term: str) -> bool:
    """Busca ``term`` como palavra inteira, ignorando caixa e acento.

    ``contains_term("Back-end Python", "python")`` é True;
    ``contains_term("Javascript", "java")`` é False.
    """
    t = re.escape(fold(term))
    return re.search(rf"(?<![\w]){t}(?![\w])", fold(text)) is not None


_LEVEL_PATTERNS: list[tuple[Level, str]] = [
    (Level.SENIOR, r"\b(senior|sr|staff|principal|lead|lider|especialista|specialist|iii|iv)\b"),
    (Level.PLENO, r"\b(pleno|pl|mid|mid-level|ii)\b"),
    (Level.JUNIOR, r"\b(junior|jr|entry|entry-level|i)\b"),
]


def infer_level(title: str) -> Level | None:
    """Nível a partir do título. Faixa fica com o menor nível (``"Pleno/Sênior"`` → PLENO),
    porque a vaga aceita esse nível; o LLM avalia o resto."""
    t = fold(title)
    found = [level for level, pattern in _LEVEL_PATTERNS if re.search(pattern, t)]
    return found[-1] if found else None


_WORK_MODEL_PATTERNS: list[tuple[WorkModel, str]] = [
    (WorkModel.HIBRIDO, r"\b(hibrido|hybrid)\b"),
    (WorkModel.REMOTO, r"\b(remoto|remote|home office|anywhere|100% remoto)\b"),
    (WorkModel.PRESENCIAL, r"\b(presencial|on-site|onsite|in office)\b"),
]


def infer_work_model(*texts: str | None) -> WorkModel | None:
    blob = fold(" ".join(t for t in texts if t))
    for model, pattern in _WORK_MODEL_PATTERNS:
        if re.search(pattern, blob):
            return model
    return None
