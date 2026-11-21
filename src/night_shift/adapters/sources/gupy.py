"""Gupy: não há API pública de busca (o endpoint antigo do portal responde 404).

A página de busca do portal (Next.js) embute as vagas em ``__NEXT_DATA__``; lemos dali.
Só a primeira página (~12 vagas) por termo, então usamos vários termos. É a fonte mais
frágil: se a Gupy mudar o front, este adapter quebra e o pipeline segue com as outras.
"""

import json
import re
from collections.abc import Iterator
from datetime import datetime
from urllib.parse import quote, urlparse

from night_shift.adapters.sources.html_text import html_to_text
from night_shift.adapters.sources.http import PoliteClient
from night_shift.domain.enums import Source, WorkModel
from night_shift.domain.job import JobPosting
from night_shift.ports import SourceError

SEARCH_URL = "https://portal.gupy.io/job-search/term={term}"
_NEXT_DATA = re.compile(r'<script id="__NEXT_DATA__"[^>]*>(.*?)</script>', re.S)
_WORKPLACE = {
    "remote": WorkModel.REMOTO,
    "hybrid": WorkModel.HIBRIDO,
    "on-site": WorkModel.PRESENCIAL,
}


def parse_search_page(html: str) -> list[dict]:
    m = _NEXT_DATA.search(html)
    if not m:
        raise SourceError("Gupy: __NEXT_DATA__ não encontrado (layout do portal mudou?)")
    try:
        data = json.loads(m.group(1))
        return data["props"]["pageProps"]["initialJobList"]["data"]
    except (ValueError, KeyError, TypeError) as e:
        raise SourceError(f"Gupy: formato inesperado em __NEXT_DATA__: {e}") from e


def _company_from_url(job_url: str) -> str:
    """``https://vemproitau.gupy.io/job/...`` → ``vemproitau``.

    O ``careerPageName`` da busca nem sempre é o nome da empresa, o subdomínio é estável.
    """
    host = urlparse(job_url).hostname or ""
    return host.removesuffix(".gupy.io") or "gupy"


def _location(j: dict) -> str | None:
    parts = [p for p in (j.get("city"), j.get("state")) if p]
    return ", ".join(parts) or None


class GupySource:
    name = "gupy"

    def __init__(self, http: PoliteClient, terms: list[str]) -> None:
        self.http, self.terms = http, terms

    def fetch(self) -> Iterator[JobPosting]:
        seen: set[str] = set()
        for term in self.terms:
            html = self.http.get(SEARCH_URL.format(term=quote(term))).text
            for j in parse_search_page(html):
                job_id = str(j["id"])
                if job_id in seen:
                    continue
                seen.add(job_id)
                published = j.get("publishedDate")
                yield JobPosting(
                    source=Source.GUPY,
                    external_id=job_id,
                    company_name=_company_from_url(j["jobUrl"]),
                    title=j["name"].strip(),
                    description=html_to_text(j.get("description")),
                    url=j["jobUrl"],
                    location=_location(j),
                    work_model=_WORKPLACE.get(j.get("workplaceType") or ""),
                    published_at=(
                        datetime.fromisoformat(published.replace("Z", "+00:00"))
                        if published
                        else None
                    ),
                )
