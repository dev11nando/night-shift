"""Filtros por regra (custo zero) aplicados antes de embeddings e LLM."""

from dataclasses import dataclass

from night_shift.config import Preferences
from night_shift.domain.enums import WorkModel
from night_shift.domain.job import JobPosting
from night_shift.domain.text import contains_term, fold, infer_level

# Títulos que contêm "engineer"/"desenvolvedor" mas não são o perfil.
DEFAULT_OFF_PROFILE = [
    "estagio",
    "estagiario",
    "intern",
    "internship",
    "trainee",
    "aprendiz",
    "sales",
    "vendas",
    "comercial",
    "pre-sales",
    "presales",
    "solutions engineer",
    "support engineer",
    "suporte",
    "designer",
    "product manager",
    "gerente",
    "manager",
    "head",
    "leader",
    "director",
    "diretor",
    "coordenador",
    "recruiter",
    "ios",
    "android",
    "mobile",
    "qa",
    "quality assurance",
    "salesforce",
    "sap",
]


@dataclass(frozen=True)
class FilterResult:
    passed: bool
    reason: str | None = None


PASS = FilterResult(True)


class HardFilter:
    def __init__(self, prefs: Preferences) -> None:
        self.prefs = prefs
        self.blocked = DEFAULT_OFF_PROFILE + prefs.blocked_keywords

    def evaluate(self, job: JobPosting) -> FilterResult:
        title = job.title

        if not any(contains_term(title, k) for k in self.prefs.title_keywords):
            return FilterResult(False, "título fora do perfil")

        for term in self.blocked:
            if contains_term(title, term):
                return FilterResult(False, f"título bloqueado: {term}")

        level = job.level or infer_level(title)
        allowed = self.prefs.stack_levels.get(job.stack or "", self.prefs.levels)
        if level is not None and level not in allowed:
            suffix = f" para {job.stack}" if job.stack in self.prefs.stack_levels else ""
            return FilterResult(False, f"nível {level}{suffix}")

        if self.prefs.keywords:
            blob = f"{title}\n{job.description}"
            if not any(contains_term(blob, k) for k in self.prefs.keywords):
                return FilterResult(False, "nenhuma keyword da stack")

        if job.work_model is not None and job.work_model not in self.prefs.work_models:
            return FilterResult(False, f"modelo {job.work_model}")

        if not self._location_ok(job):
            return FilterResult(False, f"local: {job.location}")

        return PASS

    def _location_ok(self, job: JobPosting) -> bool:
        if job.work_model is WorkModel.REMOTO or not job.location:
            return True
        loc = fold(job.location)
        if any(fold(a) in loc for a in self.prefs.locations):
            return True
        if job.work_model is None:
            # Modelo não declarado: aceita local que indica remoto ou só o país.
            return any(contains_term(loc, t) for t in ("remoto", "remote")) or loc.strip() in {
                "brasil",
                "brazil",
            }
        # Presencial/híbrido fora das cidades aceitas é cortado.
        return False
