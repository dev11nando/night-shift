"""Leitura e validação dos arquivos pessoais em ``config/`` (gitignored).

Cada arquivo real tem um ``*.example.yaml`` versionado ao lado; ``night-shift init``
copia os exemplos que ainda não existem.
"""

import shutil
from pathlib import Path
from typing import Literal

import yaml
from pydantic import BaseModel, Field, ValidationError

from night_shift.domain.enums import Contract, Level, WorkModel

# PJ equivalente ≈ CLT bruto x 1,45 (13º, férias + 1/3, FGTS, benefícios, impostos/contador).
PJ_FACTOR = 1.45

CONFIG_FILES = ("profile", "companies", "cv_master")

# Os *.example.yaml versionados no repo (instalação editável via `uv sync`).
EXAMPLES_DIR = Path(__file__).resolve().parents[2] / "config"


class ConfigError(Exception):
    pass


# ---------------------------------------------------------------- profile.yaml


class SalaryTarget(BaseModel):
    clt_min: int = Field(gt=0, description="Pretensão mínima CLT, bruto mensal (R$).")
    pj_min: int | None = Field(default=None, gt=0, description="Se vazio, usa clt_min x 1,45.")

    @property
    def effective_pj_min(self) -> int:
        return self.pj_min or round(self.clt_min * PJ_FACTOR)


class Preferences(BaseModel):
    levels: list[Level] = [Level.PLENO, Level.JUNIOR]
    work_models: list[WorkModel] = list(WorkModel)
    contracts: list[Contract] = list(Contract)
    locations: list[str] = ["São Paulo"]
    salary: dict[Level, SalaryTarget] = {}
    title_keywords: list[str] = Field(
        default=[
            "backend",
            "back-end",
            "back end",
            "software",
            "python",
            "desenvolvedor",
            "developer",
            "engenheiro",
            "engineer",
            "engineering",
            "programador",
        ],
        description="O título precisa conter ao menos uma.",
    )
    keywords: list[str] = Field(
        default=[], description="Título ou descrição precisa conter ao menos uma (se houver)."
    )
    blocked_keywords: list[str] = Field(
        default=[], description="Título com qualquer uma é cortado."
    )
    stack_levels: dict[str, list[Level]] = Field(
        default={
            "python": [Level.JUNIOR, Level.PLENO],
            "ia": [Level.JUNIOR, Level.PLENO],
            "java": [Level.JUNIOR],
        },
        description="Níveis aceitos por stack; stack fora daqui usa `levels`.",
    )
    gupy_search_terms: list[str] = ["python", "backend python", "desenvolvedor python", "fastapi"]


class AutomationConfig(BaseModel):
    enabled: bool = Field(
        default=False, description="Kill switch: false bloqueia tudo que submete algo."
    )
    auto_apply_min_score: int = Field(default=85, ge=0, le=100)
    daily_auto_apply_limit: int = Field(default=10, ge=0)


class LLMConfig(BaseModel):
    provider: Literal["claude", "ollama"] = Field(
        default="claude",
        description="claude: Claude Code CLI com o login da assinatura (sem API key) e "
        "similaridade por palavras-chave. ollama: modelos locais para nota e embeddings.",
    )
    claude_model: str = Field(default="haiku", description="Alias ou nome completo do modelo.")
    claude_executable: str = "claude"
    time_budget_minutes: int | None = Field(
        default=120, ge=1, description="Tempo máximo da etapa de nota por execução."
    )
    local_model: str = "qwen3:8b"
    embed_model: str = "bge-m3"
    ollama_url: str = "http://localhost:11434"
    think: bool | None = Field(
        default=False,
        description="Raciocínio estendido do modelo local. None = não envia o parâmetro.",
    )
    rank_top_n: int = Field(default=30, ge=1, description="Quantas vagas vão para o LLM por noite.")
    documents_min_score: int = Field(
        default=70, ge=0, le=100, description="Nota mínima para gerar CV ajustado e carta."
    )
    documents_model: str = Field(default="haiku", description="Modelo do CV ajustado e da carta.")
    claude_daily_letters: int = Field(
        default=10, ge=0, description="Máximo de vagas com CV+carta gerados por execução."
    )
    claude_daily_outreach: int = Field(
        default=10, ge=0, description="Mensagens de outreach escritas por dia (nada é enviado)."
    )


class FixedAnswer(BaseModel):
    pattern: str = Field(description="Regex (sem diferenciar maiúsculas) aplicada ao rótulo.")
    answer: str


class ApplicationConfig(BaseModel):
    """Dados da aplicação assistida (`night-shift apply`)."""

    current_company: str | None = Field(
        default=None, description="Para o campo 'empresa atual'. Vazio = deixa para você."
    )
    answers: list[FixedAnswer] = Field(
        default=[],
        description="Respostas fixas para perguntas de texto, casadas pelo rótulo do campo.",
    )
    wait_minutes: int = Field(
        default=15, ge=1, description="Quanto tempo esperar você enviar cada formulário."
    )


class TurnOffConfig(BaseModel):
    grace_seconds: int = Field(default=30, ge=0)
    stop_ollama: bool = False


class OutreachConfig(BaseModel):
    """Seu modelo de e-mail de outreach: o LLM mantém a estrutura e o tom e só adapta o
    parágrafo que liga você à empresa. ``signature`` é como você assina (padrão: o nome)."""

    email_template: str | None = None
    signature: str | None = None


class Profile(BaseModel):
    name: str
    email: str
    outreach: OutreachConfig = OutreachConfig()
    preferences: Preferences = Preferences()
    automation: AutomationConfig = AutomationConfig()
    llm: LLMConfig = LLMConfig()
    application: ApplicationConfig = ApplicationConfig()
    turn_off: TurnOffConfig = TurnOffConfig()


# -------------------------------------------------------------- companies.yaml

Ats = Literal["greenhouse", "lever", "ashby", "gupy", "outro"]


class CompanyConfig(BaseModel):
    name: str
    sector: str | None = None
    website: str | None = None
    ats: Ats | None = None
    slug: str | None = None
    outreach_contact: str | None = None


class CompaniesFile(BaseModel):
    companies: list[CompanyConfig] = []


# -------------------------------------------------------------- cv_master.yaml


class Bullet(BaseModel):
    id: str
    text: str
    tags: list[str] = []


class Experience(BaseModel):
    company: str
    role: str
    period: str
    bullets: list[Bullet] = []


class Project(BaseModel):
    """Projeto acadêmico ou pessoal (ex.: TCC), com bullets como uma experiência."""

    name: str
    context: str | None = Field(default=None, description="Ex.: 'Projeto de conclusão · SPTech'")
    period: str | None = None
    bullets: list[Bullet] = []


class Education(BaseModel):
    school: str
    course: str
    period: str | None = None


class Language(BaseModel):
    name: str
    level: str


class Contact(BaseModel):
    phone: str | None = None
    location: str | None = None
    linkedin: str | None = None
    github: str | None = None


class CVMaster(BaseModel):
    headline: str = Field(default="", description="Ex.: 'Backend Software Engineer'.")
    contact: Contact = Contact()
    summary: str = ""
    experiences: list[Experience] = []
    projects: list[Project] = []
    education: list[Education] = []
    courses: list[str] = []
    skills: list[str] = []
    languages: list[Language] = []

    def as_text(self) -> str:
        """Texto corrido usado em embeddings e prompts."""
        lines = [self.summary.strip()]
        for exp in self.experiences:
            lines.append(f"\n{exp.role} — {exp.company} ({exp.period})")
            lines += [f"- {b.text}" for b in exp.bullets]
        for proj in self.projects:
            lines.append(f"\nProjeto: {proj.name}" + (f" ({proj.context})" if proj.context else ""))
            lines += [f"- {b.text}" for b in proj.bullets]
        if self.skills:
            lines.append("\nHabilidades: " + ", ".join(self.skills))
        for ed in self.education:
            lines.append(f"Formação: {ed.course} — {ed.school}")
        if self.courses:
            lines.append("Cursos: " + ", ".join(self.courses))
        if self.languages:
            lines.append(
                "Idiomas: " + ", ".join(f"{la.name} ({la.level})" for la in self.languages)
            )
        return "\n".join(lines).strip()


# ---------------------------------------------------------------------- loaders


def _load[M: BaseModel](path: Path, model: type[M]) -> M:
    if not path.exists():
        raise ConfigError(f"{path} não existe. Rode `night-shift init` e preencha o arquivo.")
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        return model.model_validate(data)
    except yaml.YAMLError as e:
        raise ConfigError(f"YAML inválido em {path}: {e}") from e
    except ValidationError as e:
        raise ConfigError(f"Config inválida em {path}:\n{e}") from e


def load_profile(path: Path) -> Profile:
    return _load(path, Profile)


def load_companies(path: Path) -> list[CompanyConfig]:
    return _load(path, CompaniesFile).companies


def load_cv(path: Path) -> CVMaster:
    return _load(path, CVMaster)


def bootstrap_config(config_dir: Path, examples_dir: Path = EXAMPLES_DIR) -> list[Path]:
    """Copia ``<nome>.example.yaml`` → ``<nome>.yaml`` quando o real não existe.

    Nunca sobrescreve um arquivo existente. Retorna os arquivos criados.
    """
    config_dir.mkdir(parents=True, exist_ok=True)
    created = []
    for name in CONFIG_FILES:
        real = config_dir / f"{name}.yaml"
        example = examples_dir / f"{name}.example.yaml"
        if not real.exists() and example.exists():
            shutil.copyfile(example, real)
            created.append(real)
    return created
