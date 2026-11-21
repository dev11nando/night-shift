"""Avaliação vaga x candidato: similaridade de embeddings e nota do LLM."""

import math

from pydantic import BaseModel, Field

from night_shift.config import Profile
from night_shift.domain.job import JobPosting

MAX_DESCRIPTION_CHARS = 6000


class JobFit(BaseModel):
    score: int = Field(ge=0, le=100, description="Encaixe geral de 0 a 100.")
    rationale: str = Field(description="1 a 2 frases curtas explicando a nota, em português.")
    red_flags: list[str] = Field(
        default=[],
        description="Só incompatibilidades concretas exigidas pela vaga; nunca 'não informado'.",
    )


SYSTEM_PROMPT = (
    "Você é um recrutador técnico experiente avaliando o encaixe entre um candidato e uma vaga. "
    "Seja criterioso e honesto: não infle notas, e baseie-se só no texto fornecido. "
    "Responda apenas com o JSON pedido, em português."
)


def cosine(a: list[float], b: list[float]) -> float:
    dot = sum(x * y for x, y in zip(a, b, strict=True))
    na = math.sqrt(sum(x * x for x in a))
    nb = math.sqrt(sum(y * y for y in b))
    return dot / (na * nb) if na and nb else 0.0


def job_text(job: JobPosting) -> str:
    """Texto da vaga para embedding (título repetido para pesar mais)."""
    return f"{job.title}\n{job.title} — {job.company_name}\n\n{job.description[:4000]}"


def _preferences_block(profile: Profile) -> str:
    p = profile.preferences
    lines = [
        f"- Níveis aceitos (em ordem de prioridade): {', '.join(p.levels)}",
        f"- Modelos de trabalho: {', '.join(p.work_models)}",
        f"- Contratos: {', '.join(c.upper() for c in p.contracts)}",
        f"- Presencial/híbrido só em: {', '.join(p.locations)}",
    ]
    for level, target in p.salary.items():
        lines.append(
            f"- Pretensão {level}: CLT ≥ R$ {target.clt_min} | PJ ≥ R$ {target.effective_pj_min}"
        )
    return "\n".join(lines)


def build_prompt(profile: Profile, cv_text: str, job: JobPosting) -> str:
    salary = ""
    if job.salary_min or job.salary_max:
        salary = f"\nSalário informado: {job.salary_min or '?'} a {job.salary_max or '?'}"
    return f"""## Candidato
{cv_text}

## Preferências do candidato
{_preferences_block(profile)}

## Vaga
Empresa: {job.company_name}
Título: {job.title}
Local: {job.location or "não informado"} | Modelo: {job.work_model or "não informado"}{salary}

Descrição:
{job.description[:MAX_DESCRIPTION_CHARS]}

## Como pontuar (0 a 100)
- Stack e responsabilidades (até 45): quanto o dia a dia da vaga usa o que o candidato já fez.
- Senioridade (até 20): vaga sênior/staff, ou que exige bem mais experiência que a do
  candidato, pontua baixo.
- Domínio (até 15): fintech, banco, investimentos, crédito, IA/LLM somam pontos.
- Logística (até 20): modelo de trabalho, local, idioma e salário compatíveis com as preferências.
  Compare o idioma exigido pela vaga com os idiomas do candidato.

## rationale
Uma ou duas frases curtas: o principal motivo da nota.

## red_flags
Só incompatibilidades CONCRETAS que a vaga EXIGE (não diferenciais) e que impedem ou
atrapalham muito a candidatura, cada uma em até 12 palavras. Exemplos válidos:
"exige inglês fluente", "exige 5+ anos de experiência", "stack obrigatória é Java",
"presencial em Curitiba", "vaga sênior/specialist".
NÃO são red flags: informação ausente (salário, modelo, nível ou contrato não informados),
itens marcados como diferencial/desejável, formação (tecnólogo conta como graduação) e
ferramentas que o candidato aprende rápido. Se não houver nenhuma, devolva lista vazia."""
