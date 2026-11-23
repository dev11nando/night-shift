"""Nome dos PDFs de CV: ``cv_<nome>_<perfil><idioma><3 dígitos>.pdf``.

O código só faz sentido para você: perfil 1 = python, 2 = ia, 3 = java; idioma 1 = português,
2 = inglês; os 3 dígitos são aleatórios. Ex.: ``cv_fulano_silva_11456.pdf`` é o CV Python
em português. Há um arquivo fixo por tipo de vaga (no máximo 6), usado por toda vaga daquele tipo.
"""

import random
import re
from pathlib import Path

from night_shift.domain.text import fold

STACK_CODE = {"python": 1, "ia": 2, "java": 3}
LANG_CODE = {"pt": 1, "en": 2}


def person_slug(name: str) -> str:
    """``Marcos Paixao`` → ``marcos_paixao``."""
    return re.sub(r"[^a-z0-9]+", "_", fold(name)).strip("_") or "cv"


def cv_code(stack: str | None, lang: str, rng: random.Random | None = None) -> str:
    digits = (rng or random).randint(0, 999)
    return f"{STACK_CODE.get(stack or 'python', 1)}{LANG_CODE.get(lang, 1)}{digits:03d}"


def cv_filename(name: str, stack: str | None, lang: str, rng: random.Random | None = None) -> str:
    return f"cv_{person_slug(name)}_{cv_code(stack, lang, rng)}.pdf"


def _prefix(name: str, stack: str | None, lang: str) -> str:
    return f"cv_{person_slug(name)}_{STACK_CODE.get(stack or 'python', 1)}{LANG_CODE.get(lang, 1)}"


def stable_cv_name(
    folder: Path, name: str, stack: str | None, lang: str, rng: random.Random | None = None
) -> str:
    """Nome do CV fixo daquele tipo (perfil e idioma) na pasta: se já existe um, mantém o
    mesmo nome (os 3 dígitos são sorteados uma vez só); senão sorteia um novo. Cópias extras
    do mesmo tipo, se houver, são apagadas."""
    found = sorted(folder.glob(f"{_prefix(name, stack, lang)}[0-9][0-9][0-9].pdf"))
    for extra in found[1:]:
        extra.unlink()
    return found[0].name if found else cv_filename(name, stack, lang, rng)
