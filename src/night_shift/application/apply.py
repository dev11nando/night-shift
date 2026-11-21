"""Monta os dados do candidato para a aplicação assistida a partir do profile e do CV."""

from pathlib import Path

from night_shift.adapters.applier.form_filler import Candidate
from night_shift.config import CVMaster, Profile


def _url(value: str | None) -> str | None:
    if not value:
        return None
    return value if value.startswith(("http://", "https://")) else f"https://{value}"


def build_candidate(
    profile: Profile, cv: CVMaster, resume_pdf: Path, cover_letter: str | None
) -> Candidate:
    first, _, last = profile.name.strip().partition(" ")
    return Candidate(
        first_name=first,
        last_name=last,
        email=profile.email,
        phone=cv.contact.phone,
        location=cv.contact.location,
        linkedin=_url(cv.contact.linkedin),
        github=_url(cv.contact.github),
        current_company=profile.application.current_company,
        resume_pdf=resume_pdf,
        cover_letter=cover_letter,
        answers=profile.application.answers,
    )
