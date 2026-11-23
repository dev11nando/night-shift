"""Nome dos PDFs de CV: cv_<nome>_<perfil><idioma><3 dígitos>.pdf."""

import random
import re

from night_shift.config import Profile
from night_shift.domain.naming import cv_filename, person_slug, stable_cv_name


def test_codes_per_stack_and_language():
    rng = random.Random(1)
    assert re.fullmatch(
        r"cv_marcos_paixao_11\d{3}\.pdf", cv_filename("Marcos Paixao", "python", "pt", rng)
    )
    assert re.fullmatch(
        r"cv_marcos_paixao_22\d{3}\.pdf", cv_filename("Marcos Paixao", "ia", "en", rng)
    )
    assert re.fullmatch(
        r"cv_marcos_paixao_31\d{3}\.pdf", cv_filename("Marcos Paixao", "java", "pt", rng)
    )
    assert cv_filename("Marcos Paixao", None, "pt", rng).startswith("cv_marcos_paixao_11")


def test_random_part_is_three_digits_even_when_small():
    class Zero(random.Random):
        def randint(self, a, b):
            return 7

    assert cv_filename("Marcos Paixao", "python", "pt", Zero()) == "cv_marcos_paixao_11007.pdf"


def test_person_slug_and_short_name():
    assert person_slug("Marcos Paixão") == "marcos_paixao"
    assert (
        Profile(name="Marcos Fernando Araujo da Paixao", email="m@x.com").short_name
        == "Marcos Paixao"
    )
    signed = Profile(name="Marcos F", email="m@x.com", outreach={"signature": "Marcos Paixao"})
    assert signed.short_name == "Marcos Paixao"


def test_stable_name_keeps_existing_and_drops_extra_copies(tmp_path):
    for name in (
        "cv_marcos_paixao_11123.pdf",
        "cv_marcos_paixao_11999.pdf",
        "cv_marcos_paixao_12123.pdf",
    ):
        (tmp_path / name).write_bytes(b"%PDF")
    assert stable_cv_name(tmp_path, "Marcos Paixao", "python", "pt") == "cv_marcos_paixao_11123.pdf"
    assert sorted(p.name for p in tmp_path.iterdir()) == [
        "cv_marcos_paixao_11123.pdf",
        "cv_marcos_paixao_12123.pdf",
    ]
    new = stable_cv_name(tmp_path, "Marcos Paixao", "java", "en")
    assert re.fullmatch(r"cv_marcos_paixao_32\d{3}\.pdf", new)
