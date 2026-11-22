"""CV ajustado por vaga sem inventar nada.

O LLM devolve só uma *seleção*: quais bullets de cada experiência, em que ordem, quais
habilidades e um resumo curto. O texto dos bullets sempre vem do CV mestre. Este módulo
valida a seleção e monta o CV final; qualquer coisa fora do CV mestre é rejeitada.
"""

from dataclasses import dataclass

from pydantic import BaseModel, Field

from night_shift.config import CVMaster, Experience
from night_shift.domain.text import contains_term

MAX_SKILLS = 14
MIN_BULLETS = 1

# Tecnologias que um resumo inventado costuma citar. Se o resumo menciona uma delas e o CV
# mestre não, a seleção é rejeitada.
TECH_LEXICON = [
    "java", "kotlin", "golang", "go", "rust", "c#", ".net", "node", "node.js", "nestjs",
    "typescript", "javascript", "react", "angular", "vue", "php", "ruby", "rails", "scala",
    "spark", "kafka", "kubernetes", "k8s", "terraform", "gcp", "azure", "django", "flask",
    "postgresql", "postgres", "mongodb", "redis", "elasticsearch", "airflow", "databricks",
    "snowflake", "langchain", "langgraph", "pytorch", "tensorflow", "graphql", "grpc",
    "spring", "laravel", "swift", "flutter",
]  # fmt: skip


class ExperienceSelection(BaseModel):
    company: str
    bullet_ids: list[str] = Field(description="IDs dos bullets, do mais relevante para a vaga.")


class CVSelection(BaseModel):
    summary: str = Field(description="2 a 3 frases, só com fatos do CV.")
    experiences: list[ExperienceSelection]
    skills: list[str] = Field(description="Subconjunto das habilidades, mais relevantes primeiro.")


class SelectionError(ValueError):
    pass


@dataclass(frozen=True)
class TailoredCV:
    """CV pronto para renderizar: experiências com bullets já em texto."""

    master: CVMaster
    summary: str
    experiences: list[Experience]
    skills: list[str]


def invented_terms(text: str, cv: CVMaster) -> list[str]:
    reference = cv.as_text()
    return [t for t in TECH_LEXICON if contains_term(text, t) and not contains_term(reference, t)]


def apply_selection(cv: CVMaster, sel: CVSelection) -> TailoredCV:
    """Valida a seleção contra o CV mestre e monta o CV ajustado.

    Regras: toda experiência do mestre aparece (sumir com emprego cria buraco no CV), na
    ordem original; cada uma com pelo menos um bullet; só IDs existentes, sem repetição;
    habilidades só do mestre; resumo sem tecnologia que o mestre não cita.
    """
    by_company = {s.company: s for s in sel.experiences}
    experiences = []
    for exp in cv.experiences:
        chosen = by_company.get(exp.company)
        if chosen is None:
            raise SelectionError(f"experiência ausente: {exp.company}")
        bullets = {b.id: b for b in exp.bullets}
        unknown = [i for i in chosen.bullet_ids if i not in bullets]
        if unknown:
            raise SelectionError(f"bullet inexistente em {exp.company}: {', '.join(unknown)}")
        if len(set(chosen.bullet_ids)) != len(chosen.bullet_ids):
            raise SelectionError(f"bullet repetido em {exp.company}")
        if len(chosen.bullet_ids) < MIN_BULLETS:
            raise SelectionError(f"nenhum bullet em {exp.company}")
        experiences.append(
            exp.model_copy(update={"bullets": [bullets[i] for i in chosen.bullet_ids]})
        )

    extra = set(by_company) - {e.company for e in cv.experiences}
    if extra:
        raise SelectionError(f"experiência que não está no CV: {', '.join(sorted(extra))}")

    known_skills = {s.casefold(): s for s in cv.skills}
    unknown_skills = [s for s in sel.skills if s.casefold() not in known_skills]
    if unknown_skills:
        raise SelectionError(f"habilidade fora do CV: {', '.join(unknown_skills)}")
    skills = list(dict.fromkeys(known_skills[s.casefold()] for s in sel.skills))[:MAX_SKILLS]

    invented = invented_terms(sel.summary, cv)
    if invented:
        raise SelectionError(f"resumo cita o que não está no CV: {', '.join(invented)}")

    return TailoredCV(cv, sel.summary.strip() or cv.summary, experiences, skills or cv.skills)


def translation_problems(original: CVMaster, translated: CVMaster) -> list[str]:
    """Diferenças de estrutura entre o CV mestre e a tradução. Lista vazia = ok.

    A seleção do LLM é feita por ID, então os dois precisam ter as mesmas experiências, na
    mesma ordem, com os mesmos IDs de bullet, e a mesma quantidade de habilidades.
    """
    problems = []
    a, b = original.experiences, translated.experiences
    if [e.company for e in a] != [e.company for e in b]:
        problems.append(
            f"experiências diferentes: {[e.company for e in a]} x {[e.company for e in b]}"
        )
    for ea, eb in zip(a, b, strict=False):
        ids_a, ids_b = [x.id for x in ea.bullets], [x.id for x in eb.bullets]
        if ids_a != ids_b:
            missing = sorted(set(ids_a) - set(ids_b))
            extra = sorted(set(ids_b) - set(ids_a))
            detail = "ordem diferente" if not (missing or extra) else ""
            if missing:
                detail += f"faltam {missing} "
            if extra:
                detail += f"sobram {extra}"
            problems.append(f"{ea.company}: bullets não batem ({detail.strip()})")
        if ea.period != eb.period:
            problems.append(f"{ea.company}: período {ea.period} x {eb.period}")
    if len(original.skills) != len(translated.skills):
        problems.append(
            f"habilidades: {len(original.skills)} x {len(translated.skills)} na tradução"
        )
    return problems


def default_cv(cv: CVMaster) -> TailoredCV:
    """CV mestre sem ajuste: usado quando o LLM falha ou a seleção é rejeitada."""
    return TailoredCV(cv, cv.summary, list(cv.experiences), list(cv.skills))
