"""Outreach: contatos públicos, mensagem (LinkedIn + e-mail), fila e painel."""

from datetime import timedelta

import httpx
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from night_shift.adapters.contacts import ContactFinder
from night_shift.adapters.sources.http import PoliteClient, make_client
from night_shift.adapters.storage import db
from night_shift.adapters.storage.models import Company, Outreach, utcnow
from night_shift.adapters.storage.outreach import OutreachRepository
from night_shift.adapters.storage.repository import JobRepository
from night_shift.application.outreach import (
    OutreachError,
    OutreachMessage,
    linkedin_people_search,
    outreach_prompt,
    validate_outreach,
)
from night_shift.application.pipeline import Pipeline
from night_shift.config import CompanyConfig, OutreachConfig, Profile
from night_shift.domain.contacts import pick_contact, recruiting_rank, same_company
from night_shift.domain.enums import OutreachStatus
from night_shift.runtime.stop_flag import StopFlag
from night_shift.web.app import create_app, gmail_compose
from tests.test_cv import CV

PROFILE = Profile(name="Marcos Fernando", email="m@x.com")
HX = {"HX-Request": "true"}

# ---------------------------------------------------------------- contatos


@pytest.mark.parametrize(
    ("email", "rank"),
    [
        ("talentos@acme.com.br", 0),
        ("recrutamento@acme.com", 1),
        ("vagas@acme.com", 2),
        ("trabalheconosco@acme.com", 2),
        ("rh@acme.com", 5),
        ("people-br@acme.com", 5),
        ("contato@acme.com", None),
        ("imprensa@acme.com", None),
        ("joao.silva@acme.com", None),
    ],
)
def test_recruiting_rank(email, rank):
    assert recruiting_rank(email) == rank


def test_same_company_domain():
    assert same_company("talentos@nubank.com.br", "https://www.nubank.com.br")
    assert same_company("rh@jobs.nubank.com.br", "https://nubank.com.br")
    assert not same_company("rh@gupy.io", "https://nubank.com.br")
    assert not same_company("rh@asaas.com.br", "https://www.asaas.com"), "domínio diferente"


def test_pick_contact_prefers_best_recruiting_box_of_own_domain():
    emails = [
        "contato@acme.com",
        "rh@acme.com",
        "talentos@acme.com",
        "talentos@outra.com",
        "icon@2x.png",
        "maria.souza@acme.com",
    ]
    assert pick_contact(emails, "https://acme.com") == "talentos@acme.com"
    assert pick_contact(["contato@acme.com", "imprensa@acme.com"], "https://acme.com") is None


def site(routes: dict[str, httpx.Response]) -> ContactFinder:
    def handler(request):
        url = str(request.url)
        for prefix, response in routes.items():
            if url.rstrip("/") == prefix.rstrip("/"):
                return response
        return httpx.Response(404)

    return ContactFinder(PoliteClient(make_client(httpx.MockTransport(handler)), min_interval=0))


HOME = (
    '<html><head><meta name="description" content="Infraestrutura de crédito para PMEs.">'
    '</head><body><a href="/carreiras">Carreiras</a><a href="quero@acme.com">quebrado</a>'
    '<a href="mailto:contato@acme.com">Contato</a></body></html>'
)


def test_discover_follows_careers_link_and_reads_about():
    finder = site(
        {
            "https://acme.com/robots.txt": httpx.Response(200, text="User-agent: *\nAllow: /"),
            "https://acme.com": httpx.Response(200, text=HOME),
            "https://acme.com/carreiras": httpx.Response(
                200, text="<p>Mande seu CV para <a href='mailto:talentos@acme.com'>nós</a></p>"
            ),
        }
    )
    d = finder.discover("https://acme.com")
    assert d.contact == "talentos@acme.com"
    assert d.source_url == "https://acme.com/carreiras"
    assert d.careers_url == "https://acme.com/carreiras"
    assert d.about == "Infraestrutura de crédito para PMEs."
    assert not any("quero@" in p for p in d.pages), "e-mail em href não vira página"


def test_discover_respects_robots():
    finder = site(
        {
            "https://acme.com/robots.txt": httpx.Response(200, text="User-agent: *\nDisallow: /"),
            "https://acme.com": httpx.Response(200, text=HOME),
        }
    )
    d = finder.discover("https://acme.com")
    assert d.error and "robots" in d.error and d.pages == []


def test_discover_site_down():
    d = site({}).discover("https://fora.com")
    assert d.error.startswith("site não abriu")


# ---------------------------------------------------------------- mensagem

GOOD = OutreachMessage(
    linkedin_note=(
        "Oi! Sou backend Python e construí análise de crédito com LLMs. "
        "Adoraria conversar sobre o time de vocês."
    ),
    subject="Backend Python com experiência em crédito",
    email_body=(
        "Sou Marcos, backend Python.\n\nConstruí APIs em Python e análise de crédito com LLMs."
        "\n\nAtenciosamente,\nMarcos Fernando"
    ),
)


def test_valid_message():
    assert validate_outreach(GOOD, PROFILE, CV, None).linkedin_note.startswith("Oi!")


@pytest.mark.parametrize(
    ("update", "message"),
    [
        ({"linkedin_note": "x" * 301}, "301 caracteres"),
        ({"email_body": "palavra " * 170 + "Marcos"}, "longo demais"),
        ({"email_body": "Sou [Nome],\n\nMarcos"}, "campo para preencher"),
        ({"email_body": "Sou backend Python.\n\nAbraço"}, "assinatura"),
        ({"email_body": "Olá, equipe de recrutamento!\n\nSou Marcos."}, "saudação genérica"),
        ({"email_body": "Prezados,\n\nSou Marcos."}, "saudação genérica"),
        ({"email_body": "Sou Marcos e trabalhei na IORQ com crédito."}, "IORQ"),
        ({"linkedin_note": "Tenho anos de Kotlin."}, "kotlin"),
    ],
)
def test_invalid_messages(update, message):
    with pytest.raises(OutreachError, match=message):
        validate_outreach(GOOD.model_copy(update=update), PROFILE, CV, None)


TEMPLATE = (
    "Sou Marcos Paixao, engenheiro de software backend com Python.\n\n"
    "Na minha última experiência, trabalhei com FastAPI e Terraform.\n\n"
    "Acredito que tenha conexão com a Empresa.\n\nAtenciosamente,\nMarcos Paixao."
)
TEMPLATED = Profile(
    name="Marcos Fernando Araujo da Paixao",
    email="m@x.com",
    outreach={"email_template": TEMPLATE, "signature": "Marcos Paixao"},
)


def test_template_goes_into_prompt():
    prompt = outreach_prompt(TEMPLATED, CV, "Acme", "fintech", None)
    assert "Modelo do candidato" in prompt and "Na minha última experiência" in prompt
    assert "NÃO cite o nome das empresas" in prompt
    plain = outreach_prompt(PROFILE, CV, "Acme", "fintech", None)
    assert "Modelo do candidato" not in plain and 'Comece direto por "Sou Marcos' in plain


def test_template_terms_and_length_are_allowed():
    msg = GOOD.model_copy(update={"email_body": TEMPLATE.replace("Empresa", "Acme")})
    assert validate_outreach(msg, TEMPLATED, CV, None, "Acme"), "Terraform vem do modelo"
    long_template = TEMPLATED.model_copy(
        update={"outreach": OutreachConfig(email_template=TEMPLATE + " palavra" * 170)}
    )
    long_body = GOOD.model_copy(update={"email_body": TEMPLATE + " palavra" * 180})
    assert validate_outreach(long_body, long_template, CV, None, "Acme"), "limite segue o modelo"


def test_target_company_that_was_an_employer_can_be_named():
    msg = GOOD.model_copy(update={"email_body": "Sou Marcos e quero voltar à IORQ.\n\nMarcos"})
    assert validate_outreach(msg, PROFILE, CV, None, "IORQ")


def test_company_stack_from_about_is_allowed():
    msg = GOOD.model_copy(update={"linkedin_note": "Vi que vocês usam Kafka e crédito."})
    assert validate_outreach(msg, PROFILE, CV, "Plataforma em Kafka para crédito")


def test_links():
    assert "linkedin.com/search/results/people" in linkedin_people_search("Acme")
    url = gmail_compose("talentos@acme.com", "Assunto", "Corpo com acento é")
    assert (
        url.startswith("https://mail.google.com/mail/?view=cm") and "to=talentos%40acme.com" in url
    )


# ------------------------------------------------------- fila e pipeline


@pytest.fixture
def sessions(paths):
    db.upgrade(paths.db_url)
    engine = db.make_engine(paths.db_url)
    yield db.make_session_factory(engine)
    engine.dispose()


def add_companies(sessions):
    configs = [
        CompanyConfig(name="Com RH", sector="fundo", website="https://a.com"),
        CompanyConfig(name="Fintech", sector="fintech", website="https://b.com"),
        CompanyConfig(name="Manual", sector="tech", outreach_contact="eu@manual.com"),
        CompanyConfig(name="Recente", sector="fintech"),
    ]
    with sessions.begin() as s:
        ids = JobRepository(s).sync_companies(configs)
        s.get(Company, ids["Com RH"]).outreach_contact = "talentos@a.com"
        s.get(Company, ids["Recente"]).last_contacted_at = utcnow() - timedelta(days=10)
    return ids


def test_sync_keeps_discovered_contact_and_manual_wins(sessions):
    ids = add_companies(sessions)
    with sessions.begin() as s:
        JobRepository(s).sync_companies([CompanyConfig(name="Com RH", website="https://a.com")])
    with sessions() as s:
        assert s.get(Company, ids["Com RH"]).outreach_contact == "talentos@a.com"
        manual = s.get(Company, ids["Manual"])
        assert manual.contact_source_url == "config/companies.yaml"
        OutreachRepository(s).save_discovery(manual, "rh@manual.com", "https://x", None, None)
        assert manual.outreach_contact == "eu@manual.com", "descoberta não troca o manual"


def test_candidates_order_and_recontact_window(sessions):
    add_companies(sessions)
    with sessions() as s:
        names = [c.name for c in OutreachRepository(s).candidates(10)]
    assert names == ["Com RH", "Manual", "Fintech"], "com e-mail primeiro, depois setor"


class OutreachLLM:
    model = "fake"

    def __init__(self, bad=0):
        self.bad, self.calls = bad, 0

    def complete_json(self, system, prompt, schema):
        self.calls += 1
        if self.bad:
            self.bad -= 1
            return GOOD.model_copy(update={"linkedin_note": "x" * 400})
        return GOOD


@pytest.fixture
def pipeline(sessions, paths):
    return Pipeline(sessions, StopFlag(paths.run_dir), log=lambda _: None)


def test_outreach_step_respects_daily_limit_and_saves_messages(pipeline, sessions):
    add_companies(sessions)
    llm = OutreachLLM(bad=1)
    pipeline.run([lambda: pipeline.outreach(llm, PROFILE, CV, daily_limit=2)])

    with sessions() as s:
        rows = s.scalars(select(Outreach).order_by(Outreach.id)).all()
        assert [r.company.name for r in rows] == ["Com RH", "Manual"]
        assert rows[1].to_address == "eu@manual.com" and rows[0].linkedin_note == GOOD.linkedin_note
    assert llm.calls == 3, "a 1ª mensagem ruim teve uma 2ª tentativa"

    run = pipeline.run([lambda: pipeline.outreach(OutreachLLM(), PROFILE, CV, daily_limit=2)])
    assert "outreach" not in run.stats, "limite do dia já usado"


def test_discover_step_saves_results(pipeline, sessions):
    add_companies(sessions)

    class FakeFinder:
        def discover(self, website):
            from night_shift.adapters.contacts import Discovery

            return Discovery(
                website, "talentos@b.com", f"{website}/carreiras", f"{website}/carreiras", "Sobre"
            )

    run = pipeline.run([lambda: pipeline.discover_contacts(FakeFinder())])
    assert run.stats == {"companies_checked": 2, "contacts_found": 2}
    with sessions() as s:
        fintech = s.scalars(select(Company).where(Company.name == "Fintech")).one()
        assert fintech.outreach_contact == "talentos@b.com" and fintech.about == "Sobre"
        assert OutreachRepository(s).needing_discovery() == [], "varridas há menos de 30 dias"


# ---------------------------------------------------------------- painel


def test_outreach_page_and_actions(sessions):
    ids = add_companies(sessions)
    with sessions.begin() as s:
        company = s.get(Company, ids["Com RH"])
        company.careers_url = "https://a.com/carreiras"
        row = OutreachRepository(s).save_message(company, GOOD)
        oid = row.id
    client = TestClient(create_app(sessions))

    html = client.get("/outreach").text
    assert "Para enviar (1)" in html and "Com RH" in html
    assert GOOD.linkedin_note in html and "Abrir no Gmail" in html
    assert "https://a.com/carreiras" in html and "linkedin.com/search" in html
    assert 'Outreach <span class="pill">1</span>' in html

    assert client.post(f"/outreach/{oid}/sent").status_code == 403
    sent = client.post(f"/outreach/{oid}/sent", headers=HX).text
    assert "Responderam" in sent
    with sessions() as s:
        row = s.get(Outreach, oid)
        assert row.status is OutreachStatus.SENT and row.company.last_contacted_at is not None
        assert OutreachRepository(s).candidates(10)[0].name != "Com RH", "60 dias sem recontato"

    client.post(f"/outreach/{oid}/undo", headers=HX)
    with sessions() as s:
        assert s.get(Outreach, oid).company.last_contacted_at is None
    assert client.post(f"/outreach/{oid}/nada", headers=HX).status_code == 404
    assert client.post("/outreach/999/sent", headers=HX).status_code == 404
