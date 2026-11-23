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
    "emprego. Diretas e objetivas, focadas na experiência dele, específicas sobre a empresa, "
    "sem cerimônia, sem bajulação e sem inventar nada. "
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
    sig = signature(profile)
    rules = f"""- email_body: e-mail para a caixa de recrutamento da {company}. Regras fixas do
  candidato:
  * comece direto por "Sou {sig}, ..." (é assim que ele se apresenta); nada de saudação
    ou cerimônia antes ("Olá, equipe de recrutamento", "Prezados", "Espero que esteja bem");
  * tom direto e objetivo, focado no que ele fez: frases concretas sobre a experiência,
    sem floreio, adjetivos vazios ("apaixonado", "entusiasmado") ou bajulação da empresa;
  * fale da experiência, não do empregador: nunca cite o nome das empresas onde ele
    trabalhou ("na minha última experiência, trabalhei com...");
  * ligue a experiência à {company} com algo específico do setor ou da descrição dela (sem
    "pelo que a empresa diz de si"); sem descrição, fale só do setor;
  * feche colocando-se à disposição para conversar e dizendo que o currículo vai anexo;
  * termine exatamente com "Atenciosamente," e, na linha de baixo, "{sig}.\""""
    template = (profile.outreach.email_template or "").strip()
    if not template:
        return rules + "\n  * até 130 palavras, 3 ou 4 parágrafos curtos."
    return f"""{rules}
  * use o MODELO DO CANDIDATO abaixo como referência de estrutura, tom e tamanho. Não é
    para copiar: escolha as palavras e quais experiências destacar conforme a {company},
    só com fatos do modelo ou do currículo. Empresa citada no modelo é só exemplo.

### Modelo do candidato (referência)
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

Regras: na nota e no e-mail, NÃO cite o nome das empresas onde o candidato trabalhou (fale
da experiência: "na minha última experiência", "atuei com..."); experiência com data de fim já
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
    sig = signature(profile)
    if GENERIC_OPENING.match(body):
        raise OutreachError(f"e-mail abre com saudação genérica; comece direto por 'Sou {sig}'")
    if not fold(body).startswith(fold(f"Sou {sig}")):
        raise OutreachError(f"e-mail precisa começar por 'Sou {sig}, ...'")
    lines = [ln.strip() for ln in body.splitlines() if ln.strip()]
    closing = [fold(ln).rstrip(",.! ") for ln in lines[-2:]]
    if closing != ["atenciosamente", fold(sig)]:
        raise OutreachError(
            f"e-mail precisa terminar com 'Atenciosamente,' e a assinatura '{sig}.'"
        )
    if cited := _employers_cited(f"{note}\n{body}", cv, company):
        raise OutreachError(f"cita empresa onde o candidato trabalhou: {', '.join(cited)}")
    allowed = f"{about or ''}\n{template}"
    invented = [t for t in invented_terms(f"{note}\n{body}", cv) if not contains_term(allowed, t)]
    if invented:
        raise OutreachError(f"cita o que não está no CV: {', '.join(invented)}")
    return OutreachMessage(linkedin_note=note, subject=msg.subject.strip(), email_body=body)
