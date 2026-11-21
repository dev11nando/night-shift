"""Etapa de documentos: prompts, validação da carta e pipeline com LLM falso."""

import json

import pytest
from sqlalchemy import select

from night_shift.adapters.storage import db
from night_shift.adapters.storage.models import Application
from night_shift.application.documents import (
    CoverLetter,
    LetterError,
    job_language,
    letter_prompt,
    tailor_prompt,
    validate_letter,
)
from night_shift.application.pipeline import Pipeline
from night_shift.application.scoring import JobFit
from night_shift.config import Profile
from night_shift.domain.cv import CVSelection, TailoredCV
from night_shift.domain.filters import HardFilter
from night_shift.ports import LLMUnavailable
from night_shift.runtime.stop_flag import StopFlag
from tests.factories import posting
from tests.test_cv import CV
from tests.test_pipeline import BagOfWordsEmbedder, FakeSource

PROFILE = Profile(name="Marcos Fernando", email="m@x.com")
JOB = posting(description="Buscamos backend Python com FastAPI e Kafka para crédito.")
GOOD_LETTER = CoverLetter(
    subject="Candidatura: Backend Python",
    body="Olá, time.\n\nTrabalhei com FastAPI e LLMs em crédito.\n\nAbraço,\nMarcos Fernando",
)


def test_job_language():
    assert (
        job_language(
            posting(
                description="We are looking for a backend engineer with experience and the team"
            )
        )
        == "en"
    )
    assert job_language(JOB) == "pt"


def test_tailor_prompt_lists_only_catalog_ids():
    prompt = tailor_prompt(CV, JOB)
    catalog = json.loads(
        prompt.split("## Currículo (catálogo do que existe)\n")[1].split("\n\n## Vaga")[0]
    )
    assert [b["id"] for b in catalog["experiences"][0]["bullets"]] == ["apis", "aws", "llm"]
    assert "Kafka" in prompt, "descrição da vaga vai junto"


def test_letter_prompt_language_and_signature():
    assert "inglês" in letter_prompt(PROFILE, CV, JOB, "en")
    assert 'Assine apenas com "Marcos Fernando"' in letter_prompt(PROFILE, CV, JOB, "pt")


def test_valid_letter_passes_and_job_stack_is_allowed():
    letter = GOOD_LETTER.model_copy(
        update={"body": GOOD_LETTER.body.replace("time.", "time. Vi que vocês usam Kafka.")}
    )
    assert validate_letter(letter, PROFILE, CV, JOB).body.endswith("Marcos Fernando")


@pytest.mark.parametrize(
    ("body", "message"),
    [
        ("Olá [Nome do recrutador],\n\nMarcos Fernando", "campo para preencher"),
        ("palavra " * 230 + "Marcos", "longa demais"),
        ("Olá, time. Tenho anos de React.\n\nAtenciosamente", "React".lower()),
        ("Olá, time.\n\nAtenciosamente", "sem a assinatura"),
    ],
)
def test_invalid_letters(body, message):
    with pytest.raises(LetterError, match=message):
        validate_letter(CoverLetter(subject="x", body=body), PROFILE, CV, JOB)


# ---------------------------------------------------------------- pipeline


class DocsLLM:
    """Responde nota, seleção ou carta conforme o schema pedido."""

    model = "fake"

    def __init__(self, bad_selection_first=False, bad_letters=0, unavailable=False):
        self.calls: list[str] = []
        self.bad_selection_first = bad_selection_first
        self.bad_letters = bad_letters
        self.unavailable = unavailable

    def complete_json(self, system, prompt, schema):
        self.calls.append(schema.__name__)
        if schema is JobFit:
            return JobFit(score=90, rationale="ok")
        if self.unavailable:
            raise LLMUnavailable("limite de uso")
        if schema is CVSelection:
            if self.bad_selection_first and self.calls.count("CVSelection") == 1:
                ids = ["apis", "inventado"]
            else:
                assert self.calls.count("CVSelection") == 1 or "rejeitada" in prompt
                ids = ["llm", "apis"]
            return CVSelection(
                summary="Backend Python.",
                experiences=[
                    {"company": "IORQ", "bullet_ids": ids},
                    {"company": "Quatá", "bullet_ids": ["web"]},
                ],
                skills=["Python"],
            )
        if self.bad_letters:
            self.bad_letters -= 1
            return CoverLetter(subject="x", body="Olá [Nome]")
        return GOOD_LETTER


@pytest.fixture
def pipeline(paths):
    db.upgrade(paths.db_url)
    engine = db.make_engine(paths.db_url)
    p = Pipeline(db.make_session_factory(engine), StopFlag(paths.run_dir), log=lambda _: None)
    yield p
    engine.dispose()


def run_docs(pipeline, tmp_path, llm, limit=5, min_score=70):
    rendered: list[TailoredCV] = []

    def render(cv, out, lang):
        rendered.append(cv)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_bytes(b"%PDF-fake")
        return out

    run = pipeline.run(
        [
            lambda: pipeline.collect([FakeSource("a", [JOB])], []),
            lambda: pipeline.screen(HardFilter(PROFILE.preferences)),
            lambda: pipeline.embed_rank(BagOfWordsEmbedder(), "python fastapi"),
            lambda: pipeline.llm_score(llm, PROFILE, "cv", top_n=5),
            lambda: pipeline.documents(llm, PROFILE, CV, render, tmp_path / "cv", min_score, limit),
        ]
    )
    return run, rendered


def application(pipeline):
    with pipeline.sessions() as s:
        return s.scalars(select(Application)).one()


def test_documents_are_generated_and_saved(pipeline, tmp_path):
    run, rendered = run_docs(pipeline, tmp_path, DocsLLM())

    assert run.stats["documents"] == 1
    assert [b.id for b in rendered[0].experiences[0].bullets] == ["llm", "apis"]
    app = application(pipeline)
    assert app.cv_variant_path.endswith("-fintech-x.pdf")
    assert app.cover_letter.endswith("Marcos Fernando")
    assert app.answers["letter_subject"] == "Candidatura: Backend Python"


def test_rejected_selection_is_retried_with_feedback(pipeline, tmp_path):
    run, rendered = run_docs(pipeline, tmp_path, DocsLLM(bad_selection_first=True))
    assert run.errors == []
    assert [b.id for b in rendered[0].experiences[0].bullets] == ["llm", "apis"]


def test_bad_letter_twice_keeps_cv_without_letter(pipeline, tmp_path):
    run, _ = run_docs(pipeline, tmp_path, DocsLLM(bad_letters=2))
    assert any("carta em" in e for e in run.errors)
    app = application(pipeline)
    assert app.cv_variant_path and app.cover_letter is None


def test_documents_are_not_regenerated(pipeline, tmp_path):
    llm = DocsLLM()
    run_docs(pipeline, tmp_path, llm)
    run2, _ = run_docs(pipeline, tmp_path, llm)
    assert "documents" not in run2.stats


def test_below_min_score_gets_no_documents(pipeline, tmp_path):
    run, rendered = run_docs(pipeline, tmp_path, DocsLLM(), min_score=95)
    assert rendered == [] and "documents" not in run.stats


def test_unavailable_llm_stops_the_stage(pipeline, tmp_path):
    run, rendered = run_docs(pipeline, tmp_path, DocsLLM(unavailable=True))
    assert run.status == "failed"
    assert rendered == []


def test_english_job_gets_english_cv(pipeline, tmp_path):
    from tests.test_cv import CV_EN

    english = posting(
        external_id="en1",
        title="Backend Python Engineer",
        description="We are looking for a backend engineer with experience in Python and the team.",
    )
    calls = []

    def render(cv, out, lang):
        calls.append((lang, out.name, cv.experiences[0].bullets[0].text))
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_bytes(b"%PDF")
        return out

    llm = DocsLLM()
    pipeline.run(
        [
            lambda: pipeline.collect([FakeSource("a", [JOB, english])], []),
            lambda: pipeline.screen(HardFilter(PROFILE.preferences)),
            lambda: pipeline.embed_rank(BagOfWordsEmbedder(), "python fastapi"),
            lambda: pipeline.llm_score(llm, PROFILE, "cv", top_n=5),
            lambda: pipeline.documents(
                llm, PROFILE, CV, render, tmp_path / "cv", 70, 5, cv_en=CV_EN
            ),
        ]
    )
    by_lang = {lang: (name, text) for lang, name, text in calls}
    assert by_lang["en"][0].endswith("-en.pdf") and by_lang["en"][1].startswith("EN ")
    assert not by_lang["pt"][0].endswith("-en.pdf") and not by_lang["pt"][1].startswith("EN ")
