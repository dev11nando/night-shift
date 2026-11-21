"""Portas (interfaces) que a aplicação usa. Adapters concretos ficam em ``adapters/``.

Ainda por vir (fases seguintes): Applier, CVRenderer, MailDrafts.
"""

from collections.abc import Iterable
from typing import Protocol

from pydantic import BaseModel

from night_shift.domain.job import JobPosting


class SourceError(Exception):
    """Falha de uma fonte; o pipeline registra e segue para a próxima."""


class JobSource(Protocol):
    name: str

    def fetch(self) -> Iterable[JobPosting]: ...


class Embedder(Protocol):
    model: str

    def embed(self, texts: list[str]) -> list[list[float]]: ...


class LLMProvider(Protocol):
    model: str

    def complete_json[T: BaseModel](self, system: str, prompt: str, schema: type[T]) -> T: ...


class LLMUnavailable(Exception):
    """Modelo/servidor fora do ar: o pipeline para a etapa de LLM, sem falhar o resto."""
