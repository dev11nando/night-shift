"""Mensagem de outreach para uma EMPRESA (não uma vaga): nota de conexão do LinkedIn e
versão e-mail. Fluxo diferente da carta de candidatura (application/documents.py)."""

import re
from urllib.parse import quote_plus

from pydantic import BaseModel, Field

from night_shift.config import CVMaster, Profile
from night_shift.domain.cv import invented_terms
from night_shift.domain.text import contains_term, fold

LINKEDIN_NOTE_LIMIT = 300  # limite do próprio LinkedIn para nota de convite
MAX_EMAIL_WORDS = 160

SYSTEM = (
    "Você escreve mensagens curtas de networking para um engenheiro de software que procura "
    "emprego. Diretas, específicas sobre a empresa, sem bajulação e sem inventar nada. "
    "Responda apenas com o JSON pedido."
)

SECTOR_LABEL = {
    "banco_digital": "banco digital",
    "fintech": "fintech",
    "fundo": "investimentos",
    "ia": "dados e IA",
    "tech": "tecnologia",
}


class OutreachMessage(BaseModel):
    linkedin_note: str = Field(description="Nota de conexão do LinkedIn, no máximo 300 caracteres.")
    subject: str = Field(description="Assunto do e-mail, curto.")
    email_body: str = Field(description="E-mail, parágrafos separados por linha em branco.")


class OutreachError(ValueError):
    pass


def linkedin_people_search(company: str) -> str:
    """Busca de pessoas no LinkedIn (você abre e escolhe a quem mandar; nada é raspado)."""
    keywords = f'"{company}" (tech recruiter OR talent acquisition OR engineering manager)'
    return f"https://www.linkedin.com/search/results/people/?keywords={quote_plus(keywords)}"


def outreach_prompt(
    profile: Profile, cv: CVMaster, company: str, sector: str | None, about: str | None
) -> str:
    context = about or "sem descrição disponível; não invente nada sobre a empresa"
    return f"""## Candidato: {profile.name}
{cv.as_text()}

## Empresa
Nome: {company}
Setor: {SECTOR_LABEL.get(sector or "", sector or "não informado")}
O que ela diz de si (site): {context}

## Tarefa
Não há vaga específica: o objetivo é abrir uma conversa sobre oportunidades de backend.

- linkedin_note: nota de convite para alguém de recrutamento ou liderança técnica da
  {company}. No MÁXIMO 300 caracteres contando espaços. Sem saudação com nome (não sabemos
  quem vai receber). Diga quem é o candidato em poucas palavras, ligue UMA experiência real
  dele ao que a {company} faz e peça para conversar.
- subject: assunto curto do e-mail, sem clichê.
- email_body: até 130 palavras, 2 ou 3 parágrafos curtos, para a caixa de recrutamento da
  empresa: quem é, por que a {company} (algo específico do setor ou da descrição), 1 ou 2
  realizações reais do currículo, disponibilidade para conversar e que o CV vai anexo.
  Assine só com "{profile.name}".

Regras: experiência com data de fim já acabou (fale no passado); não aponte lacunas; não
invente experiência, número, tecnologia ou fato sobre a empresa; nada de colchetes ou campos
para preencher; português do Brasil."""


def validate_outreach(
    msg: OutreachMessage, profile: Profile, cv: CVMaster, about: str | None
) -> OutreachMessage:
    note, body = msg.linkedin_note.strip(), msg.email_body.strip()
    if len(note) > LINKEDIN_NOTE_LIMIT:
        raise OutreachError(f"nota do LinkedIn com {len(note)} caracteres (máximo 300)")
    words = len(body.split())
    if words > MAX_EMAIL_WORDS:
        raise OutreachError(f"e-mail longo demais ({words} palavras)")
    for text in (note, body, msg.subject):
        if re.search(r"\[[^\]]*\]|\{[^}]*\}|<[^>]*>", text):
            raise OutreachError("mensagem com campo para preencher")
    if fold(profile.name.split()[0]) not in fold(body):
        raise OutreachError("e-mail sem a assinatura do candidato")
    invented = [
        t for t in invented_terms(f"{note}\n{body}", cv) if not (about and contains_term(about, t))
    ]
    if invented:
        raise OutreachError(f"cita o que não está no CV: {', '.join(invented)}")
    return OutreachMessage(linkedin_note=note, subject=msg.subject.strip(), email_body=body)
