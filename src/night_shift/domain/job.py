import hashlib
import re
from dataclasses import dataclass
from datetime import datetime

from night_shift.domain.enums import Contract, Level, Source, WorkModel


@dataclass(frozen=True)
class JobPosting:
    """Vaga como veio da fonte, já normalizada para texto puro."""

    source: Source
    external_id: str
    company_name: str
    title: str
    description: str
    url: str
    location: str | None = None
    work_model: WorkModel | None = None
    contract: Contract | None = None
    level: Level | None = None
    stack: str | None = None
    salary_min: int | None = None
    salary_max: int | None = None
    published_at: datetime | None = None

    @property
    def content_hash(self) -> str:
        """Mesma vaga publicada em duas fontes gera o mesmo hash."""
        raw = f"{self.company_name} {self.title} {self.description[:2000]}"
        norm = re.sub(r"\W+", " ", raw.casefold()).strip()
        return hashlib.sha256(norm.encode()).hexdigest()
