"""Fontes contra respostas gravadas no formato real das APIs (conferido em 21/11/2026)."""

import json

import httpx
import pytest

from night_shift.adapters.sources import build_sources
from night_shift.adapters.sources.ats import AshbySource, GreenhouseSource, LeverSource
from night_shift.adapters.sources.gupy import GupySource, parse_search_page
from night_shift.adapters.sources.html_text import html_to_text
from night_shift.adapters.sources.http import PoliteClient, make_client
from night_shift.config import CompanyConfig, Preferences
from night_shift.domain.enums import Source, WorkModel
from night_shift.ports import SourceError

GREENHOUSE = {
    "jobs": [
        {
            "id": 8638232002,
            "title": " Engenheiro(a) de Software Backend ",
            "absolute_url": "https://job-boards.greenhouse.io/acme/jobs/8638232002",
            "location": {"name": "São Paulo, Brazil (Hybrid)"},
            # O Greenhouse devolve o HTML escapado.
            "content": (
                "&lt;p&gt;Python &amp;amp; FastAPI&lt;/p&gt;"
                "&lt;ul&gt;&lt;li&gt;AWS&lt;/li&gt;&lt;/ul&gt;"
            ),
            "first_published": "2026-07-22T13:38:40-04:00",
            "company_name": "Acme",
        }
    ],
    "meta": {"total": 1},
}

LEVER = [
    {
        "id": "6ed76ce8",
        "text": "Backend Developer",
        "hostedUrl": "https://jobs.lever.co/acme/6ed76ce8",
        "categories": {"location": "São Paulo, SP", "commitment": "Full-time"},
        "workplaceType": "remote",
        "descriptionPlain": "Sobre a vaga",
        "lists": [{"text": "Requisitos", "content": "<li>Python</li><li>SQL</li>"}],
        "additionalPlain": "Benefícios",
        "salaryRange": {
            "min": 7000,
            "max": 9000,
            "currency": "BRL",
            "interval": "per-month-salary",
        },
        "createdAt": 1786469891368,
    },
    {
        "id": "usd",
        "text": "Engineer",
        "hostedUrl": "https://jobs.lever.co/acme/usd",
        "categories": {},
        "salaryRange": {
            "min": 120000,
            "max": 150000,
            "currency": "USD",
            "interval": "per-year-salary",
        },
    },
]

ASHBY = {
    "jobs": [
        {
            "id": "34413f8d",
            "title": "Software Engineer, Backend",
            "location": "São Paulo",
            "workplaceType": "Hybrid",
            "isRemote": False,
            "isListed": True,
            "jobUrl": "https://jobs.ashbyhq.com/acme/34413f8d",
            "descriptionPlain": "Python, Kafka",
            "publishedAt": "2026-04-07T17:12:35.753+00:00",
        },
        {"id": "hidden", "title": "x", "isListed": False, "jobUrl": "u"},
    ]
}

GUPY_JOB = {
    "id": 12898791,
    "name": "Desenvolvedor Python",
    "description": "<p>Python e Django</p>",
    "careerPageName": "ADMINISTRADOR DE REDES",
    "workplaceType": "remote",
    "city": "",
    "state": "",
    "jobUrl": "https://vagasstefanini.gupy.io/job/eyJqb2JJZCI6MTI4OTg3OTF9",
    "publishedDate": "2026-11-19T14:25:08.428Z",
}


def gupy_html(jobs: list[dict]) -> str:
    data = {"props": {"pageProps": {"initialJobList": {"data": jobs}}}}
    script = f'<script id="__NEXT_DATA__" type="application/json">{json.dumps(data)}</script>'
    return f"<html>{script}</html>"


def client_for(routes: dict[str, httpx.Response]) -> PoliteClient:
    def handler(request: httpx.Request) -> httpx.Response:
        for prefix, response in routes.items():
            if str(request.url).startswith(prefix):
                return response
        return httpx.Response(404)

    return PoliteClient(make_client(httpx.MockTransport(handler)), min_interval=0)


ACME = CompanyConfig(name="Acme", slug="acme")


def test_greenhouse_unescapes_html_and_infers_model():
    http = client_for(
        {
            "https://boards-api.greenhouse.io/v1/boards/acme/jobs": httpx.Response(
                200, json=GREENHOUSE
            )
        }
    )
    [job] = GreenhouseSource(http, ACME).fetch()

    assert job.source is Source.GREENHOUSE
    assert job.external_id == "8638232002"
    assert job.title == "Engenheiro(a) de Software Backend"
    assert job.company_name == "Acme"
    assert "Python & FastAPI" in job.description and "- AWS" in job.description
    assert job.work_model is WorkModel.HIBRIDO
    assert job.published_at.year == 2026


def test_lever_keeps_only_monthly_brl_salary():
    http = client_for({"https://api.lever.co/v0/postings/acme": httpx.Response(200, json=LEVER)})
    brl, usd = LeverSource(http, ACME).fetch()

    assert (brl.salary_min, brl.salary_max) == (7000, 9000)
    assert brl.work_model is WorkModel.REMOTO
    assert "Requisitos" in brl.description and "- Python" in brl.description
    assert usd.salary_min is None


def test_ashby_skips_unlisted():
    http = client_for(
        {"https://api.ashbyhq.com/posting-api/job-board/acme": httpx.Response(200, json=ASHBY)}
    )
    [job] = AshbySource(http, ACME).fetch()

    assert job.work_model is WorkModel.HIBRIDO
    assert job.url == "https://jobs.ashbyhq.com/acme/34413f8d"


def test_gupy_dedupes_across_terms_and_uses_subdomain_as_company():
    http = client_for(
        {"https://portal.gupy.io/job-search/": httpx.Response(200, text=gupy_html([GUPY_JOB]))}
    )
    jobs = list(GupySource(http, ["python", "backend"]).fetch())

    assert len(jobs) == 1
    assert jobs[0].company_name == "vagasstefanini"
    assert jobs[0].description == "Python e Django"
    assert jobs[0].work_model is WorkModel.REMOTO
    assert jobs[0].location is None


def test_gupy_layout_change_is_a_source_error():
    with pytest.raises(SourceError, match="__NEXT_DATA__"):
        parse_search_page("<html>novo layout</html>")


def test_http_errors_become_source_errors():
    http = client_for({})
    with pytest.raises(SourceError, match="404"):
        list(GreenhouseSource(http, ACME).fetch())


def test_build_sources_skips_companies_without_board():
    companies = [
        ACME.model_copy(update={"ats": "greenhouse"}),
        CompanyConfig(name="Só outreach"),
        CompanyConfig(name="Sem slug", ats="lever"),
    ]
    sources = build_sources(client_for({}), companies, Preferences(gupy_search_terms=["python"]))
    assert [s.name for s in sources] == ["greenhouse:acme", "gupy"]


def test_html_to_text_handles_empty():
    assert html_to_text(None) == ""
