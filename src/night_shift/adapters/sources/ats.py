"""Job boards públicos de ATS: Greenhouse, Lever e Ashby. Um source por empresa."""

from collections.abc import Iterator
from datetime import UTC, datetime

from night_shift.adapters.sources.html_text import html_to_text
from night_shift.adapters.sources.http import PoliteClient
from night_shift.config import CompanyConfig
from night_shift.domain.enums import Source, WorkModel
from night_shift.domain.job import JobPosting
from night_shift.domain.text import infer_work_model

_WORKPLACE = {
    "remote": WorkModel.REMOTO,
    "hybrid": WorkModel.HIBRIDO,
    "onsite": WorkModel.PRESENCIAL,
    "on-site": WorkModel.PRESENCIAL,
}


def _workplace(value: str | None, *fallback_texts: str | None) -> WorkModel | None:
    if value and value.casefold() in _WORKPLACE:
        return _WORKPLACE[value.casefold()]
    return infer_work_model(*fallback_texts)


def _int(value) -> int | None:
    return int(value) if isinstance(value, int | float) else None


def _iso(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


class GreenhouseSource:
    def __init__(self, http: PoliteClient, company: CompanyConfig) -> None:
        self.http, self.company = http, company
        self.name = f"greenhouse:{company.slug}"

    def fetch(self) -> Iterator[JobPosting]:
        url = f"https://boards-api.greenhouse.io/v1/boards/{self.company.slug}/jobs"
        data = self.http.get_json(url, content="true")
        for j in data.get("jobs", []):
            location = (j.get("location") or {}).get("name")
            yield JobPosting(
                source=Source.GREENHOUSE,
                external_id=str(j["id"]),
                company_name=self.company.name,
                title=j["title"].strip(),
                description=html_to_text(j.get("content"), escaped=True),
                url=j["absolute_url"],
                location=location,
                work_model=infer_work_model(location, j["title"]),
                published_at=_iso(j.get("first_published") or j.get("updated_at")),
            )


class LeverSource:
    def __init__(self, http: PoliteClient, company: CompanyConfig) -> None:
        self.http, self.company = http, company
        self.name = f"lever:{company.slug}"

    def fetch(self) -> Iterator[JobPosting]:
        url = f"https://api.lever.co/v0/postings/{self.company.slug}"
        for j in self.http.get_json(url, mode="json"):
            cats = j.get("categories") or {}
            location = cats.get("location")
            sections = "\n\n".join(
                f"{s.get('text', '')}\n{html_to_text(s.get('content'))}" for s in j.get("lists", [])
            )
            description = "\n\n".join(
                p for p in (j.get("descriptionPlain"), sections, j.get("additionalPlain")) if p
            )
            salary = j.get("salaryRange") or {}
            # Só aproveitamos faixa mensal em reais; anual/USD confundiria a comparação.
            monthly = salary.get("interval") == "per-month-salary" and salary.get("currency") in (
                None,
                "BRL",
            )
            created = j.get("createdAt")
            yield JobPosting(
                source=Source.LEVER,
                external_id=j["id"],
                company_name=self.company.name,
                title=j["text"].strip(),
                description=description.strip(),
                url=j["hostedUrl"],
                location=location,
                work_model=_workplace(j.get("workplaceType"), location, j["text"]),
                salary_min=_int(salary.get("min")) if monthly else None,
                salary_max=_int(salary.get("max")) if monthly else None,
                published_at=datetime.fromtimestamp(created / 1000, UTC) if created else None,
            )


class AshbySource:
    def __init__(self, http: PoliteClient, company: CompanyConfig) -> None:
        self.http, self.company = http, company
        self.name = f"ashby:{company.slug}"

    def fetch(self) -> Iterator[JobPosting]:
        url = f"https://api.ashbyhq.com/posting-api/job-board/{self.company.slug}"
        data = self.http.get_json(url, includeCompensation="true")
        for j in data.get("jobs", []):
            if j.get("isListed") is False:
                continue
            location = j.get("location")
            work_model = _workplace(j.get("workplaceType"), location, j["title"])
            if work_model is None and j.get("isRemote"):
                work_model = WorkModel.REMOTO
            yield JobPosting(
                source=Source.ASHBY,
                external_id=j["id"],
                company_name=self.company.name,
                title=j["title"].strip(),
                description=(j.get("descriptionPlain") or html_to_text(j.get("descriptionHtml"))),
                url=j["jobUrl"],
                location=location,
                work_model=work_model,
                published_at=_iso(j.get("publishedAt")),
            )


ATS_SOURCES = {"greenhouse": GreenhouseSource, "lever": LeverSource, "ashby": AshbySource}
