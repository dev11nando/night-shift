import pytest

from night_shift.adapters.render.cv_pdf import format_period, render_cv_pdf
from night_shift.config import CVMaster
from night_shift.domain.cv import (
    CVSelection,
    ExperienceSelection,
    SelectionError,
    apply_selection,
    default_cv,
    invented_terms,
)

CV = CVMaster.model_validate(
    {
        "headline": "Backend Software Engineer",
        "contact": {"phone": "(11) 90000-0000", "location": "São Paulo"},
        "summary": "Engenheiro backend Python com AWS e LLMs.",
        "experiences": [
            {
                "company": "IORQ",
                "role": "Engenheiro de Software",
                "period": "2024-02/2026-08",
                "bullets": [
                    {"id": "apis", "text": "APIs em Python com FastAPI."},
                    {"id": "aws", "text": "Serverless na AWS com Lambda e SQS."},
                    {"id": "llm", "text": "Análise de crédito com LLMs."},
                ],
            },
            {
                "company": "Quatá",
                "role": "Desenvolvedor Full Stack",
                "period": "2023-02/2024-01",
                "bullets": [{"id": "web", "text": "Aplicações web para o mercado financeiro."}],
            },
        ],
        "education": [{"school": "SPTech", "course": "ADS", "period": "2022-08/2024-06"}],
        "skills": ["Python", "FastAPI", "AWS Lambda", "LLMs", "Docker"],
        "languages": [{"name": "Inglês", "level": "intermediário"}],
    }
)


def selection(**overrides) -> CVSelection:
    base = {
        "summary": "Backend Python focado em crédito com LLMs e AWS.",
        "experiences": [
            {"company": "IORQ", "bullet_ids": ["llm", "apis"]},
            {"company": "Quatá", "bullet_ids": ["web"]},
        ],
        "skills": ["LLMs", "python", "FastAPI"],
    }
    return CVSelection.model_validate(base | overrides)


def test_selection_reorders_and_keeps_master_text():
    cv = apply_selection(CV, selection())

    assert [b.id for b in cv.experiences[0].bullets] == ["llm", "apis"]
    assert cv.experiences[0].bullets[0].text == "Análise de crédito com LLMs."
    assert [e.company for e in cv.experiences] == ["IORQ", "Quatá"]
    assert cv.skills == ["LLMs", "Python", "FastAPI"], "grafia do CV mestre, não a do LLM"


@pytest.mark.parametrize(
    ("overrides", "message"),
    [
        ({"experiences": [{"company": "IORQ", "bullet_ids": ["apis"]}]}, "ausente: Quatá"),
        (
            {
                "experiences": [
                    {"company": "IORQ", "bullet_ids": ["apis", "kafka-lead"]},
                    {"company": "Quatá", "bullet_ids": ["web"]},
                ]
            },
            "inexistente",
        ),
        (
            {
                "experiences": [
                    {"company": "IORQ", "bullet_ids": ["apis", "apis"]},
                    {"company": "Quatá", "bullet_ids": ["web"]},
                ]
            },
            "repetido",
        ),
        (
            {
                "experiences": [
                    {"company": "IORQ", "bullet_ids": []},
                    {"company": "Quatá", "bullet_ids": ["web"]},
                ]
            },
            "nenhum bullet",
        ),
        (
            {
                "experiences": [
                    {"company": "IORQ", "bullet_ids": ["apis"]},
                    {"company": "Quatá", "bullet_ids": ["web"]},
                    {"company": "Google", "bullet_ids": ["x"]},
                ]
            },
            "não está no CV: Google",
        ),
        ({"skills": ["Python", "Kubernetes"]}, "habilidade fora do CV: Kubernetes"),
        ({"summary": "Backend com Java e Kafka em produção."}, "java, kafka"),
    ],
)
def test_selection_rejects_anything_not_in_master(overrides, message):
    with pytest.raises(SelectionError, match=message):
        apply_selection(CV, selection(**overrides))


def test_invented_terms_ignores_what_master_has():
    assert invented_terms("Python, FastAPI e AWS", CV) == []
    assert invented_terms("React e TypeScript", CV) == ["typescript", "react"]


def test_default_cv_is_master_unchanged():
    cv = default_cv(CV)
    assert cv.summary == CV.summary
    assert [len(e.bullets) for e in cv.experiences] == [3, 1]


def test_format_period():
    assert format_period("2024-02/2026-08") == "Fev/2024 – Ago/2026"  # noqa: RUF001
    assert format_period("2020") == "2020"
    assert format_period(None) == ""


def test_render_pdf(tmp_path):
    out = render_cv_pdf(
        apply_selection(CV, selection()), "Fulano de Tal", "f@x.com", tmp_path / "cv.pdf"
    )

    data = out.read_bytes()
    assert data.startswith(b"%PDF")
    assert len(data) > 2_000


def test_experience_selection_requires_company():
    with pytest.raises(ValueError):
        ExperienceSelection.model_validate({"bullet_ids": []})
