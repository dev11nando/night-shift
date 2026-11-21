"""Que campo de formulário é qual, só pelo rótulo. Sem navegador: dá para testar puro.

A regra de ouro: campo sensível nunca é preenchido pelo sistema, mesmo que exista uma
resposta configurada que case com ele.
"""

import re
from dataclasses import dataclass
from enum import StrEnum

from night_shift.config import FixedAnswer
from night_shift.domain.text import fold


class Field(StrEnum):
    FIRST_NAME = "first_name"
    LAST_NAME = "last_name"
    FULL_NAME = "full_name"
    EMAIL = "email"
    PHONE = "phone"
    LOCATION = "location"
    LINKEDIN = "linkedin"
    GITHUB = "github"
    CURRENT_COMPANY = "current_company"
    COVER_LETTER = "cover_letter"
    RESUME = "resume"


# Documento, dados demográficos e de saúde: só você responde.
SENSITIVE = re.compile(
    r"\b(cpf|rg|cnh|passaporte|passport|ssn|social security|documento|"
    r"raca|etnia|race|ethnic|cor\b|genero|gender|sexo|orientacao|sexual|"
    r"deficiencia|disability|neurodivers|pcd|pronome|pronoun|idade|age\b|"
    r"nascimento|birth|religi|veteran|criminal|antecedente)",
)

# Ordem importa: o primeiro que casar vence.
_RULES: list[tuple[Field, re.Pattern]] = [
    (Field.LAST_NAME, re.compile(r"sobrenome|last name|surname|family name")),
    (Field.FIRST_NAME, re.compile(r"^(primeiro nome|first name|given name)$")),
    # Rótulo inteiro, para "Nome da empresa" não virar nome da pessoa.
    (Field.FULL_NAME, re.compile(r"^(full name|nome completo|name|nome|seu nome|your name)$")),
    (Field.EMAIL, re.compile(r"e-?mail")),
    (Field.PHONE, re.compile(r"phone|telefone|celular|whatsapp|mobile")),
    (Field.LINKEDIN, re.compile(r"linkedin")),
    (Field.GITHUB, re.compile(r"github")),
    (Field.CURRENT_COMPANY, re.compile(r"current company|empresa atual|current employer")),
    (Field.LOCATION, re.compile(r"localiza|location|cidade|^city")),
    (
        Field.COVER_LETTER,
        re.compile(
            r"cover letter|carta de apresenta|additional information|informac.es adicionais"
        ),
    ),
    (Field.RESUME, re.compile(r"resume|curriculo|\bcv\b")),
]


@dataclass(frozen=True)
class Classified:
    field: Field | None = None
    sensitive: bool = False
    answer: str | None = None  # resposta fixa configurada


def normalize_label(label: str) -> str:
    """Tira asterisco/✱ de obrigatório, dois-pontos e espaços: ``"Nome*"`` → ``"nome"``."""
    return re.sub(r"[*✱:]+", " ", fold(label)).strip()


def classify(label: str, answers: list[FixedAnswer], has_last_name_field: bool) -> Classified:
    norm = normalize_label(label)
    if not norm:
        return Classified()
    if SENSITIVE.search(norm):
        return Classified(sensitive=True)
    for field, pattern in _RULES:
        if pattern.search(norm):
            # "Nome" sozinho é primeiro nome quando o formulário tem "Sobrenome" separado.
            if field is Field.FULL_NAME and has_last_name_field:
                return Classified(Field.FIRST_NAME)
            return Classified(field)
    for fixed in answers:
        if re.search(fixed.pattern, norm, re.IGNORECASE) or re.search(
            fixed.pattern, label, re.IGNORECASE
        ):
            return Classified(answer=fixed.answer)
    return Classified()


CONFIRMATION = re.compile(
    r"thank you for (applying|your application|your interest)|"
    r"application (has been |was )?(received|submitted)|"
    r"we('ve| have) received your application|"
    r"obrigad[oa] (por (se candidatar|sua candidatura|seu interesse))|"
    r"candidatura (foi )?(enviada|recebida|realizada)",
    re.IGNORECASE,
)


def is_confirmation(text: str) -> bool:
    return CONFIRMATION.search(text) is not None
