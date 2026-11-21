import pytest

from night_shift.config import Preferences
from night_shift.domain.enums import Level, WorkModel
from night_shift.domain.filters import HardFilter
from tests.factories import posting

PREFS = Preferences(
    levels=[Level.PLENO, Level.JUNIOR],
    locations=["São Paulo"],
    keywords=["python", "fastapi"],
    blocked_keywords=["php"],
)


def check(**overrides):
    return HardFilter(PREFS).evaluate(posting(**overrides))


def test_good_job_passes():
    assert check().passed


@pytest.mark.parametrize(
    ("overrides", "reason_part"),
    [
        ({"title": "Analista Financeiro"}, "título fora do perfil"),
        ({"title": "Sales Engineer"}, "sales"),
        ({"title": "Estágio em Desenvolvimento Python"}, "estagio"),
        ({"title": "Desenvolvedor PHP Pleno"}, "php"),
        ({"title": "Senior Backend Engineer"}, "nível senior"),
        (
            {"title": "Desenvolvedor Backend Pleno", "description": "Stack: Java, Spring, Kafka."},
            "keyword",
        ),
        (
            {"location": "Curitiba, PR", "work_model": WorkModel.PRESENCIAL},
            "local",
        ),
        ({"location": "Miami, FL", "work_model": None}, "local"),
    ],
)
def test_rejections_explain_why(overrides, reason_part):
    result = check(**overrides)
    assert not result.passed
    assert reason_part in result.reason


def test_remote_ignores_location():
    assert check(location="Recife, PE", work_model=WorkModel.REMOTO).passed


def test_unknown_level_passes_to_llm():
    assert check(title="Backend Engineer").passed


def test_unknown_model_accepts_country_only_location():
    assert check(location="Brasil", work_model=None).passed


def test_work_model_outside_preferences_is_cut():
    prefs = PREFS.model_copy(update={"work_models": [WorkModel.REMOTO]})
    result = HardFilter(prefs).evaluate(posting(work_model=WorkModel.PRESENCIAL))
    assert not result.passed
