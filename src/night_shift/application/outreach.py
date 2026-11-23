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


GENERIC_OPENING = re.compile(r"^\s*(ol[aá]|oi|prezad[oa]s?|car[oa]s?|bom dia|boa tarde)\b", re.I)


def signature(profile: Profile) -> str:
    return (profile.outreach.signature or profile.name).strip()


def _email_instructions(profile: Profile, company: str) -> str:
    template = (profile.outreach.email_template or "").strip()
    if not template:
        return f"""- email_body: até 130 palavras, 2 ou 3 parágrafos curtos, para a caixa de
  recrutamento da empresa. Comece direto por "Sou {signature(profile)}, ..." (sem saudação
  como "Olá, equipe"): quem é, 1 ou 2 realizações reais do currículo, por que a {company}
  (algo específico do setor ou da descrição), disponibilidade para conversar e que o CV vai
  anexo. Termine com "Atenciosamente," e "{signature(profile)}"."""
    return f"""- email_body: use o MODELO DO CANDIDATO abaixo como base. Mantenha a abertura, os
  parágrafos sobre a experiência, o fechamento e a assinatura praticamente iguais (pode
  mudar a ordem ou o destaque dos itens de experiência para o que mais conversa com a
  {company}, só com fatos do modelo ou do currículo). Reescreva o parágrafo que liga o
  candidato à empresa para a {company}, com algo específico do setor ou da descrição dela,
  no mesmo tamanho do parágrafo do modelo (1 ou 2 frases, sem "pelo que a empresa diz de
  si"); se não houver descrição, fale só do setor. Não acrescente saudação no início.

### Modelo do candidato
{template}"""


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
{_email_instructions(profile, company)}

Regras: no e-mail, NÃO cite o nome das empresas onde o candidato trabalhou (fale da
experiência: "na minha última experiência", "atuei com..."); experiência com data de fim já
acabou (fale no passado); não aponte lacunas; não invente experiência, número, tecnologia ou
fato sobre a empresa; nada de colchetes ou campos para preencher; português do Brasil."""


def _employers_cited(body: str, cv: CVMaster, target: str | None) -> list[str]:
    """Empregadores do CV citados no e-mail (o candidato prefere falar só da experiência).
    A empresa-alvo não conta, caso seja um ex-empregador."""
    target_f = fold(target or "")
    return [
        e.company
        for e in cv.experiences
        if contains_term(body, e.company) and fold(e.company) not in target_f
    ]


def validate_outreach(
    msg: OutreachMessage,
    profile: Profile,
    cv: CVMaster,
    about: str | None,
    company: str | None = None,
) -> OutreachMessage:
    note, body = msg.linkedin_note.strip(), msg.email_body.strip()
    template = profile.outreach.email_template or ""
    if len(note) > LINKEDIN_NOTE_LIMIT:
        raise OutreachError(f"nota do LinkedIn com {len(note)} caracteres (máximo 300)")
    words = len(body.split())
    max_words = max(MAX_EMAIL_WORDS, len(template.split()) + 40)
    if words > max_words:
        raise OutreachError(f"e-mail longo demais ({words} palavras)")
    for text in (note, body, msg.subject):
        if re.search(r"\[[^\]]*\]|\{[^}]*\}|<[^>]*>", text):
            raise OutreachError("mensagem com campo para preencher")
    if GENERIC_OPENING.match(body):
        raise OutreachError("e-mail abre com saudação genérica; comece direto por 'Sou ...'")
    if fold(signature(profile).split()[0]) not in fold(body):
        raise OutreachError("e-mail sem a assinatura do candidato")
    if cited := _employers_cited(body, cv, company):
        raise OutreachError(f"e-mail cita empresa onde o candidato trabalhou: {', '.join(cited)}")
    allowed = f"{about or ''}\n{template}"
    invented = [t for t in invented_terms(f"{note}\n{body}", cv) if not contains_term(allowed, t)]
    if invented:
        raise OutreachError(f"cita o que não está no CV: {', '.join(invented)}")
    return OutreachMessage(linkedin_note=note, subject=msg.subject.strip(), email_body=body)
