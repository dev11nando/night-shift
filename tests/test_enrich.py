import pytest

from night_shift.domain.enrich import enrich
from night_shift.domain.enums import Contract, Level
from night_shift.domain.text import extract_salary, infer_contract
from tests.factories import posting


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("Salário: R$ 6.000,00 a R$ 8.500,00 + benefícios", (6000, 8500)),
        ("Remuneração R$7.500", (7500, None)),
        ("faixa R$ 5000 - R$ 7000", (5000, 7000)),
        ("VR de R$ 800 por mês; salário R$ 9.000", (9000, None)),
        ("Pacote anual de R$ 180.000", (None, None)),
        ("sem salário informado", (None, None)),
    ],
)
def test_extract_salary(text, expected):
    assert extract_salary(text) == expected


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("Contratação CLT - Home Office", Contract.CLT),
        ("Modelo de contratação: PJ", Contract.PJ),
        ("Aceitamos CLT ou PJ", None),
        ("Vaga remota", None),
        ("Profissional com experiência em DJANGO e pjax", None),
    ],
)
def test_infer_contract(text, expected):
    assert infer_contract(text) is expected


def test_enrich_fills_only_missing_fields():
    job = enrich(
        posting(
            title="Desenvolvedor Python Pleno",
            description="Contratação PJ. Remuneração R$ 9.000 a R$ 11.000.",
        )
    )
    assert (job.level, job.contract, job.salary_min, job.salary_max) == (
        Level.PLENO,
        Contract.PJ,
        9000,
        11000,
    )

    from_source = posting(salary_min=7000, salary_max=None, description="R$ 1.500 de VR")
    assert enrich(from_source).salary_min == 7000, "salário da fonte não é sobrescrito"
