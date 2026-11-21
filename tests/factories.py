from dataclasses import replace

from night_shift.domain.enums import Source, WorkModel
from night_shift.domain.job import JobPosting

_BASE = JobPosting(
    source=Source.GREENHOUSE,
    external_id="1",
    company_name="Fintech X",
    title="Desenvolvedor Backend Python Pleno",
    description="Buscamos pessoa com experiência em Python, FastAPI e AWS (Lambda, SQS).",
    url="https://example.com/jobs/1",
    location="São Paulo, SP",
    work_model=WorkModel.HIBRIDO,
)


def posting(**overrides) -> JobPosting:
    return replace(_BASE, **overrides)
