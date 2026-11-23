"""Nome dos PDFs de CV: ``cv_<nome>_<perfil><idioma><3 dígitos>.pdf``.

O código só faz sentido para você: perfil 1 = python, 2 = ia, 3 = java; idioma 1 = português,
2 = inglês; os 3 dígitos são aleatórios. Ex.: ``cv_fulano_silva_11456.pdf`` é o CV Python
em português. O recrutador vê só o nome; quem é qual fica no banco e no painel.
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


def clear_cv_variants(folder: Path, name: str, stack: str | None, lang: str) -> None:
    """Apaga as versões anteriores do mesmo perfil e idioma (o sufixo aleatório muda a cada
    geração; sem isso, a pasta acumularia cópias)."""
    prefix = f"cv_{person_slug(name)}_{STACK_CODE.get(stack or 'python', 1)}{LANG_CODE[lang]}"
    for old in folder.glob(f"{prefix}[0-9][0-9][0-9].pdf"):
        old.unlink()
