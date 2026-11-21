"""Prompts e validação dos documentos por vaga: seleção do CV e carta de apresentação."""

import json
import re

from pydantic import BaseModel, Field

from night_shift.config import CVMaster, Profile
from night_shift.domain.cv import invented_terms
from night_shift.domain.job import JobPosting
from night_shift.domain.text import contains_term, fold

MAX_DESCRIPTION_CHARS = 5000
MAX_LETTER_WORDS = 220

TAILOR_SYSTEM = (
    "Você adapta currículos para vagas específicas sem inventar nada. Só escolhe e ordena "
    "itens que já existem no currículo. Responda apenas com o JSON pedido."
)

LETTER_SYSTEM = (
    "Você escreve cartas de apresentação curtas, específicas e honestas para vagas de "
    "tecnologia. Nunca inventa experiências, números ou tecnologias. Responda apenas com o "
    "JSON pedido."
)


class CoverLetter(BaseModel):
    subject: str = Field(description="Assunto curto para e-mail, ex.: 'Candidatura: <vaga>'.")
    body: str = Field(description="Texto da carta, parágrafos separados por linha em branco.")


class LetterError(ValueError):
    pass


_EN_WORDS = {"the", "and", "you", "with", "our", "will", "experience", "team", "we", "are"}
_PT_WORDS = {"de", "e", "com", "para", "você", "experiência", "time", "nossa", "vaga", "uma"}


def job_language(job: JobPosting) -> str:
    """``"en"`` ou ``"pt"`` pela frequência de palavras comuns de cada idioma."""
    words = re.findall(r"[a-zà-ú]+", f"{job.title} {job.description[:3000]}".casefold())
    en = sum(w in _EN_WORDS for w in words)
    pt = sum(w in _PT_WORDS for w in words)
    return "en" if en > pt * 1.2 else "pt"


def _job_block(job: JobPosting) -> str:
    return (
        f"Empresa: {job.company_name}\nTítulo: {job.title}\n"
        f"Local: {job.location or 'não informado'}\n\n"
        f"Descrição:\n{job.description[:MAX_DESCRIPTION_CHARS]}"
    )


def tailor_prompt(cv: CVMaster, job: JobPosting) -> str:
    catalog = {
        "summary_original": cv.summary.strip(),
        "experiences": [
            {
                "company": e.company,
                "role": e.role,
                "bullets": [{"id": b.id, "text": b.text} for b in e.bullets],
            }
            for e in cv.experiences
        ],
        "skills": cv.skills,
    }
    return f"""## Currículo (catálogo do que existe)
{json.dumps(catalog, ensure_ascii=False, indent=1)}

## Vaga
{_job_block(job)}

## Tarefa
Monte a seleção do currículo para esta vaga:
- experiences: TODAS as empresas do catálogo, com o nome exatamente igual. Para cada uma,
  `bullet_ids` com os IDs mais relevantes para a vaga primeiro (pode omitir os irrelevantes,
  mas mantenha pelo menos 2 quando existirem). Use só IDs do catálogo.
- skills: até 14 habilidades do catálogo, escritas exatamente como estão, mais relevantes primeiro.
- summary: 2 a 3 frases em português reescrevendo o resumo original com ênfase no que a vaga
  pede. Use SÓ fatos do catálogo: não cite tecnologia, empresa, número ou tempo de
  experiência que não esteja lá."""


def letter_prompt(profile: Profile, cv: CVMaster, job: JobPosting, lang: str) -> str:
    language = "inglês" if lang == "en" else "português do Brasil"
    return f"""## Candidato: {profile.name}
{cv.as_text()}

## Vaga
{_job_block(job)}

## Tarefa
Escreva a carta de apresentação em {language}:
- No máximo 170 palavras, 3 parágrafos curtos, tom direto e profissional.
- 1º: por que esta vaga/empresa, citando algo específico da descrição.
- 2º: 1 ou 2 realizações do currículo que mais se ligam ao que a vaga pede, sem exagerar.
- 3º: fechamento curto com disponibilidade para conversar.
- Assine apenas com "{profile.name}".
- Experiência com data de fim no período (ex.: 2024-02/2026-08) já acabou: fale dela no
  passado ("desenvolvi", "atuei"), nunca no presente.
- Fale só do que o candidato tem. Não aponte lacunas, não diga que falta alguma
  tecnologia e não se desculpe por nada; a carta não é lugar para isso.
- Proibido: inventar experiência, número, métrica ou tecnologia que não esteja no currículo;
  clichês ("venho por meio desta", "apaixonado por desafios"); colchetes ou campos para
  preencher.
- subject: "Candidatura: <título da vaga>" (em inglês se a carta for em inglês)."""


def validate_letter(
    letter: CoverLetter, profile: Profile, cv: CVMaster, job: JobPosting
) -> CoverLetter:
    body = letter.body.strip()
    # Citar a stack da vaga é legítimo; tecnologia que não está nem no CV nem na vaga é invenção.
    invented = [t for t in invented_terms(body, cv) if not contains_term(job.description, t)]
    if invented:
        raise LetterError(f"carta cita o que não está no CV: {', '.join(invented)}")
    if re.search(r"\[[^\]]*\]|\{[^}]*\}|<[^>]*>", body):
        raise LetterError("carta com campo para preencher")
    words = len(body.split())
    if words > MAX_LETTER_WORDS:
        raise LetterError(f"carta longa demais ({words} palavras)")
    if fold(profile.name.split()[0]) not in fold(body):
        raise LetterError("carta sem a assinatura do candidato")
    return CoverLetter(subject=letter.subject.strip(), body=body)
