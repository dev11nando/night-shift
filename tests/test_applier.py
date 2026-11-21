"""Aplicação assistida contra formulários locais que imitam Greenhouse e Lever."""

import pytest
from playwright.sync_api import sync_playwright

from night_shift.adapters.applier.assisted import apply_url, wait_for_confirmation
from night_shift.adapters.applier.form_filler import Candidate, fill_form
from night_shift.config import FixedAnswer
from night_shift.domain.enums import Source
from night_shift.domain.form_fields import Field, classify, is_confirmation

GREENHOUSE_LIKE = """<!doctype html><html><body><form id="f">
  <label for="first_name">Nome*</label><input id="first_name" required>
  <label for="last_name">Sobrenome*</label><input id="last_name" required>
  <label for="email">E-mail*</label><input id="email" type="text" required>
  <label for="phone">Telefone*</label><input id="phone" type="tel" required>
  <label for="loc">Localização (Cidade)*</label><input id="loc" required>
  <label for="resume">Anexar</label><input id="resume" type="file">
  <label for="q1">CPF:*</label><input id="q1" required>
  <label for="q2">Qual é a sua raça/etnia?*</label><input id="q2" required>
  <label for="q3">LinkedIn:</label><input id="q3">
  <label for="q4">Pretensão salarial*</label><input id="q4" required>
  <label for="cl">Cover Letter</label><textarea id="cl"></textarea>
  <iframe src="data:text/html,recaptcha-enterprise"></iframe>
  <button type="submit">Enviar</button>
</form></body></html>"""

LEVER_LIKE = """<!doctype html><html><body><form>
  <label>Full name ✱<input name="name" required></label>
  <label>Email ✱<input name="email" type="email" required></label>
  <label>Phone ✱<input name="phone" required></label>
  <label>Current company ✱<input name="org" required></label>
  <label>LinkedIn URL ✱<input name="urls[LinkedIn]" required></label>
  <input type="file" name="resume" id="resume-upload-input">
  <fieldset><legend>Disponível para híbrido?</legend>
    <label><input type="radio" name="cards[x][field0]" value="Sim" required>Sim</label>
    <label><input type="radio" name="cards[x][field0]" value="Não" required>Não</label>
  </fieldset>
  <label>Nome da empresa onde estudou<input name="school"></label>
</form></body></html>"""

ANSWERS = [FixedAnswer(pattern=r"pretens|salary", answer="R$ 6.000 CLT")]


@pytest.fixture
def resume(tmp_path):
    pdf = tmp_path / "cv.pdf"
    pdf.write_bytes(b"%PDF-1.4 cv")
    return pdf


@pytest.fixture
def cand(resume):
    return Candidate(
        first_name="Marcos",
        last_name="Fernando Paixao",
        email="m@x.com",
        phone="(11) 90000-0000",
        location="São Paulo, SP",
        linkedin="https://linkedin.com/in/m",
        github=None,
        current_company="IORQ",
        resume_pdf=resume,
        cover_letter="Olá, time.\n\nMarcos",
        answers=ANSWERS,
    )


@pytest.fixture(scope="module")
def browser():
    with sync_playwright() as p:
        b = p.chromium.launch()
        yield b
        b.close()


# ------------------------------------------------------------------- rótulos


@pytest.mark.parametrize(
    ("label", "has_last", "expected"),
    [
        ("Nome*", True, Field.FIRST_NAME),
        ("Nome", False, Field.FULL_NAME),
        ("Full name ✱", False, Field.FULL_NAME),
        ("Sobrenome*", True, Field.LAST_NAME),
        ("E-mail*", False, Field.EMAIL),
        ("Phone Number", False, Field.PHONE),
        ("LinkedIn URL ✱", False, Field.LINKEDIN),
        ("Current company ✱", False, Field.CURRENT_COMPANY),
        ("Nome da empresa atual", False, Field.CURRENT_COMPANY),
        ("Localização (Cidade)*", False, Field.LOCATION),
        ("Resume/CV ATTACH RESUME/CV", False, Field.RESUME),
        ("Additional information", False, Field.COVER_LETTER),
    ],
)
def test_classify_fields(label, has_last, expected):
    assert classify(label, [], has_last).field is expected


@pytest.mark.parametrize(
    "label",
    [
        "CPF:*",
        "Qual é a sua raça/etnia?*",
        "Qual é a sua identidade de gênero?*",
        "Qual é a sua orientação sexual?*",
        "Você possui alguma deficiência/neurodiversidade?*",
        "Por favor, compartilhe quais pronomes você utiliza.",
        "Data de nascimento",
    ],
)
def test_sensitive_fields_are_never_filled_even_with_answer(label):
    trap = [FixedAnswer(pattern=".*", answer="qualquer coisa")]
    c = classify(label, trap, False)
    assert c.sensitive and c.answer is None and c.field is None


def test_cidade_is_not_mistaken_for_idade():
    assert classify("Cidade", [], False).field is Field.LOCATION


def test_fixed_answer_by_label():
    assert classify("Pretensão salarial*", ANSWERS, False).answer == "R$ 6.000 CLT"
    assert classify("Pergunta qualquer", ANSWERS, False).answer is None


@pytest.mark.parametrize(
    ("text", "ok"),
    [
        ("Thank you for applying to Acme!", True),
        ("Your application has been submitted.", True),
        ("Obrigado por se candidatar!", True),
        ("Sua candidatura foi enviada com sucesso", True),
        ("Apply for this job", False),
    ],
)
def test_confirmation_text(text, ok):
    assert is_confirmation(text) is ok


def test_apply_urls():
    assert apply_url(Source.GREENHOUSE, "stone", "123") == (
        "https://job-boards.greenhouse.io/stone/jobs/123"
    )
    assert apply_url(Source.LEVER, "neon", "ab").endswith("/neon/ab/apply")
    assert apply_url(Source.ASHBY, "nubank", "x").endswith("/nubank/x/application")
    assert apply_url(Source.GUPY, "x", "1") is None
    assert apply_url(Source.GREENHOUSE, None, "1") is None


# ------------------------------------------------------------- no navegador


def test_fill_greenhouse_like(browser, cand):
    page = browser.new_page()
    page.set_content(GREENHOUSE_LIKE)
    report = fill_form(page, cand)

    assert page.input_value("#first_name") == "Marcos"
    assert page.input_value("#last_name") == "Fernando Paixao"
    assert page.input_value("#email") == "m@x.com"
    assert page.input_value("#q3") == "https://linkedin.com/in/m"
    assert page.input_value("#q4") == "R$ 6.000 CLT"
    assert page.input_value("#cl").startswith("Olá, time.")
    assert page.input_value("#q1") == "", "CPF nunca é preenchido"
    assert page.input_value("#q2") == "", "raça nunca é preenchida"
    assert report.resume_attached
    assert page.eval_on_selector("#resume", "el => el.files[0].name") == "cv.pdf"
    assert set(report.sensitive_skipped) == {"CPF:*", "Qual é a sua raça/etnia?*"}
    assert set(report.unanswered_required) == {"CPF:*", "Qual é a sua raça/etnia?*"}
    assert report.captcha == "recaptcha"
    page.close()


def test_fill_lever_like(browser, cand):
    page = browser.new_page()
    page.set_content(LEVER_LIKE)
    report = fill_form(page, cand)

    assert page.input_value("[name=name]") == "Marcos Fernando Paixao"
    assert page.input_value("[name=org]") == "IORQ"
    assert page.input_value("[name=school]") == "", "não confunde com nome da pessoa"
    assert report.resume_attached, "sem rótulo claro: usa o primeiro upload"
    assert len(report.unanswered_required) == 1, "a pergunta de rádio fica para você"
    assert report.captcha is None
    page.close()


def test_existing_value_is_not_overwritten(browser, cand):
    page = browser.new_page()
    page.set_content('<label for="e">Email</label><input id="e" value="outro@x.com">')
    fill_form(page, cand)
    assert page.input_value("#e") == "outro@x.com"
    page.close()


def test_wait_for_confirmation(browser):
    page = browser.new_page()
    page.set_content(
        "<div id='b'>Formulário</div><script>"
        "setTimeout(() => document.getElementById('b').innerText ="
        " 'Obrigado por se candidatar!', 300)</script>"
    )
    assert wait_for_confirmation(page, 5, poll_s=0.1) == "applied"

    page.set_content("<div>Formulário</div>")
    assert wait_for_confirmation(page, 0.3, poll_s=0.1) == "timeout"

    page.close()
    assert wait_for_confirmation(page, 5, poll_s=0.1) == "skipped"


def test_required_by_asterisk_only_is_reported(browser, cand):
    page = browser.new_page()
    page.set_content(
        '<input id="u" placeholder="Nome da Universidade *">'
        '<input id="g" aria-label="Grau *">'
        '<input id="o" placeholder="Orientação Sexual Afetiva - opcional">'
        '<div style="display:none"><input id="h" placeholder="Escondido *"></div>'
    )
    report = fill_form(page, cand)
    assert report.unanswered_required == ["Nome da Universidade *", "Grau *"]
    page.close()
