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
    translation_problems,
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


# ------------------------------------------------------------- versão em inglês

CV_EN = CV.model_copy(
    update={
        "summary": "Backend engineer with Python, AWS and LLMs.",
        "experiences": [
            e.model_copy(
                update={
                    "role": "Software Engineer",
                    "bullets": [b.model_copy(update={"text": f"EN {b.text}"}) for b in e.bullets],
                }
            )
            for e in CV.experiences
        ],
        "skills": ["Python", "FastAPI", "AWS Lambda", "LLMs", "Docker"],
    }
)


def test_translation_ok():
    assert translation_problems(CV, CV_EN) == []


def test_translation_problems_are_explained():
    iorq = CV_EN.experiences[0]
    missing = iorq.model_copy(update={"bullets": iorq.bullets[:2]})
    reordered = iorq.model_copy(update={"bullets": list(reversed(iorq.bullets))})
    other_period = CV_EN.experiences[1].model_copy(update={"period": "2023-03/2024-01"})

    def with_exps(*exps):
        return CV_EN.model_copy(update={"experiences": list(exps)})

    assert "faltam ['llm']" in translation_problems(CV, with_exps(missing, other_period))[0]
    assert "período" in translation_problems(CV, with_exps(iorq, other_period))[0]
    assert (
        "ordem diferente" in translation_problems(CV, with_exps(reordered, CV_EN.experiences[1]))[0]
    )
    assert "experiências diferentes" in translation_problems(CV, with_exps(iorq))[0]
    fewer_skills = CV_EN.model_copy(update={"skills": ["Python"]})
    assert "habilidades" in translation_problems(CV, fewer_skills)[0]


def test_format_period_english():
    assert format_period("2024-02/2026-08", "en") == "Feb 2024 – Aug 2026"  # noqa: RUF001


def test_render_english_pdf(tmp_path):
    out = render_cv_pdf(default_cv(CV_EN), "Fulano", "f@x.com", tmp_path / "cv-en.pdf", "en")
    assert out.read_bytes().startswith(b"%PDF")


def test_full_cv_keeps_every_skill():
    many = CV.model_copy(update={"skills": [f"skill{i}" for i in range(20)]})
    assert len(default_cv(many).skills) == 20, "o CV completo não corta habilidades"


# ------------------------------------------------------- perfis e 1 página

from night_shift.adapters.render.cv_pdf import page_count, render_cv_pdf_info  # noqa: E402
from night_shift.config import Project  # noqa: E402


def test_project_section_and_translation_check():
    proj = Project.model_validate(
        {"name": "TCC", "context": "SPTech", "bullets": [{"id": "tcc", "text": "Java"}]}
    )
    pt = CV.model_copy(update={"projects": [proj]})
    assert "Projeto: TCC (SPTech)" in pt.as_text()
    assert translation_problems(pt, CV_EN)[0].startswith("projetos não batem")
    assert translation_problems(pt, CV_EN.model_copy(update={"projects": [proj]})) == []


def test_render_always_fits_one_page(tmp_path):
    long_exp = CV.experiences[0].model_copy(
        update={
            "bullets": [
                b.model_copy(update={"id": f"b{i}", "text": "Texto longo de realização. " * 14})
                for i, b in enumerate(CV.experiences[0].bullets * 12)
            ]
        }
    )
    huge = CV.model_copy(update={"experiences": [long_exp, CV.experiences[1]]})
    info = render_cv_pdf_info(default_cv(huge), "Fulano", "f@x.com", tmp_path / "x.pdf")
    assert page_count(info.path) == 1
    assert info.scale < 1 and info.dropped_courses and info.trimmed_bullets > 0


def test_short_cv_keeps_full_size(tmp_path):
    info = render_cv_pdf_info(default_cv(CV), "Fulano", "f@x.com", tmp_path / "x.pdf")
    assert (info.scale, info.dropped_courses, info.trimmed_bullets) == (1.0, False, 0)
    assert page_count(info.path) == 1
