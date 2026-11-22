from dataclasses import replace

from night_shift.domain.job import JobPosting
from night_shift.domain.stacks import classify_stack
from night_shift.domain.text import extract_salary, infer_contract, infer_level


def enrich(job: JobPosting) -> JobPosting:
    """Completa nível, contrato, salário e stack a partir do texto quando a fonte não informa."""
    changes = {}
    if job.stack is None:
        changes["stack"] = classify_stack(job.title, job.description)
    if job.level is None:
        changes["level"] = infer_level(job.title)
    if job.contract is None:
        changes["contract"] = infer_contract(job.title, job.description)
    if job.salary_min is None and job.salary_max is None:
        changes["salary_min"], changes["salary_max"] = extract_salary(job.description)
    return replace(job, **changes) if changes else job
