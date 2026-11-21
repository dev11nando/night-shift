"""Leitura e validação dos arquivos pessoais em ``config/`` (gitignored).

Cada arquivo real tem um ``*.example.yaml`` versionado ao lado; ``night-shift init``
copia os exemplos que ainda não existem.
"""

import shutil
from pathlib import Path

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
    keywords: list[str] = []
    blocked_keywords: list[str] = []


class AutomationConfig(BaseModel):
    enabled: bool = Field(
        default=False, description="Kill switch: false bloqueia tudo que submete algo."
    )
    auto_apply_min_score: int = Field(default=85, ge=0, le=100)
    daily_auto_apply_limit: int = Field(default=10, ge=0)


class LLMConfig(BaseModel):
    local_model: str = "qwen3:8b"
    ollama_url: str = "http://localhost:11434"
    claude_daily_letters: int = Field(default=10, ge=0)
    claude_daily_outreach: int = Field(default=5, ge=0)


class TurnOffConfig(BaseModel):
    grace_seconds: int = Field(default=30, ge=0)
    stop_ollama: bool = False


class Profile(BaseModel):
    name: str
    email: str
    preferences: Preferences = Preferences()
    automation: AutomationConfig = AutomationConfig()
    llm: LLMConfig = LLMConfig()
    turn_off: TurnOffConfig = TurnOffConfig()


def load_profile(path: Path) -> Profile:
    if not path.exists():
        raise ConfigError(f"{path} não existe. Rode `night-shift init` e preencha o arquivo.")
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        return Profile.model_validate(data)
    except yaml.YAMLError as e:
        raise ConfigError(f"YAML inválido em {path}: {e}") from e
    except ValidationError as e:
        raise ConfigError(f"Config inválida em {path}:\n{e}") from e


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
