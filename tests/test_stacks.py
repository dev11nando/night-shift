"""Perfis por stack: classificação da vaga, filtro por nível e escolha do CV no pipeline."""

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from night_shift.adapters.storage import db
from night_shift.adapters.storage.models import Application, Job, Score
from night_shift.application.pipeline import Pipeline
from night_shift.application.scoring import JobFit, build_prompt
from night_shift.config import Preferences, Profile
from night_shift.domain.cv import CVSelection
from night_shift.domain.enrich import enrich
from night_shift.domain.enums import Level
from night_shift.domain.filters import HardFilter
from night_shift.domain.stacks import classify_stack
from night_shift.runtime.stop_flag import StopFlag
from night_shift.web.app import create_app
from tests.factories import posting
from tests.test_cv import CV
from tests.test_pipeline import FakeSource


@pytest.mark.parametrize(
    ("title", "description", "stack"),
    [
        ("Desenvolvedor Java Júnior", "Spring Boot, JPA", "java"),
        ("Backend Developer Java/Python", "", "java"),
        ("Engenheiro de Software Pleno - Spring Boot", "", "java"),
        ("Desenvolvedor JavaScript", "React e Node", "python"),
        ("AI Engineer", "LLMs, RAG e agentes", "ia"),
        ("Desenvolvedor de Software (IA Generativa)", "Python", "ia"),
        ("Backend Python Pleno", "FastAPI e AWS", "python"),
        ("Software Engineer", "Trabalhamos com Java e Spring Boot no backend", "java"),
        ("Software Engineer", "Python, Java e Go", "python"),
        ("Software Engineer", "LLMs e agentes de IA com Python", "ia"),
        ("Software Engineer", "Go e Rust", "python"),
        ("Backend Engineer", "Somos uma fintech que usa IA no produto. Stack: Go.", "python"),
        ("Backend Engineer", "Usamos IA no atendimento. Python e Django.", "python"),
    ],
)
def test_classify_stack(title, description, stack):
    assert classify_stack(title, description) == stack


def test_enrich_sets_stack_once():
    assert enrich(posting(title="Desenvolvedor Java Júnior", stack=None)).stack == "java"
    assert enrich(posting(stack="ia")).stack == "ia", "stack já definida não muda"


PREFS = Preferences(levels=[Level.PLENO, Level.JUNIOR], keywords=["python", "java"])


@pytest.mark.parametrize(
    ("title", "stack", "passed"),
    [
        ("Desenvolvedor Java Júnior", "java", True),
        ("Desenvolvedor Java Pleno", "java", False),
        ("Desenvolvedor Java", "java", True),  # nível desconhecido: o LLM avalia
        ("Desenvolvedor Python Pleno", "python", True),
        ("Engenheiro de IA Pleno", "ia", True),
    ],
)
def test_filter_levels_per_stack(title, stack, passed):
    result = HardFilter(PREFS).evaluate(
        posting(title=title, stack=stack, description="java python")
    )
    assert result.passed is passed
    if not passed:
        assert "para java" in result.reason


def test_prompt_shows_levels_of_the_job_stack():
    profile = Profile(name="Eu", email="e@x.com", preferences=PREFS)
    java = build_prompt(profile, "CV", posting(stack="java"))
    python = build_prompt(profile, "CV", posting(stack="python"))
    assert "Níveis aceitos para vagas de java (em ordem de prioridade): junior" in java
    assert "Níveis aceitos para vagas de python (em ordem de prioridade): junior, pleno" in python


# ---------------------------------------------------------------- pipeline

PROFILE = Profile(name="Marcos Fernando", email="m@x.com", preferences=PREFS)
CV_JAVA = CV.model_copy(update={"summary": "Perfil Java e POO.", "headline": "Java"})
JAVA_JOB = posting(
    external_id="j1", title="Desenvolvedor Java Júnior", description="java spring boot poo"
)
PY_JOB = posting(
    external_id="p1", title="Desenvolvedor Python Pleno", description="python fastapi aws"
)


class StackLLM:
    """Nota 90 sempre; anota com que CV cada vaga foi avaliada."""

    model = "fake"

    def __init__(self):
        self.score_cv: dict[str, str] = {}

    def complete_json(self, system, prompt, schema):
        if schema is JobFit:
            title = prompt.split("Título: ")[1].split("\n")[0]
            self.score_cv[title] = "java" if "Perfil Java e POO." in prompt else "python"
            return JobFit(score=90, rationale="ok")
        if schema is CVSelection:
            return CVSelection(
                summary="Resumo.",
                experiences=[
                    {"company": "IORQ", "bullet_ids": ["apis", "llm"]},
                    {"company": "Quatá", "bullet_ids": ["web"]},
                ],
                skills=["Python"],
            )
        from tests.test_documents import GOOD_LETTER

        return GOOD_LETTER


class FactoryEmbedder:
    """Fábrica de embedder por texto de CV: registra com qual CV cada grupo foi comparado."""

    def __init__(self):
        self.calls: list[str] = []

    def __call__(self, cv_text):
        self.calls.append(cv_text)
        outer = self

        class Emb:
            model = "kw"

            def embed(self, texts):
                return [[1.0, float("java" in t.casefold())] for t in texts]

        outer.last = Emb()
        return outer.last


@pytest.fixture
def pipeline(paths):
    db.upgrade(paths.db_url)
    engine = db.make_engine(paths.db_url)
    p = Pipeline(db.make_session_factory(engine), StopFlag(paths.run_dir), log=lambda _: None)
    yield p
    engine.dispose()


def test_pipeline_uses_the_profile_of_each_job(pipeline, tmp_path):
    rendered = {}

    def render(cv, out, lang):
        rendered[out.name] = cv.master.summary
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_bytes(b"%PDF")
        return out

    llm, factory = StackLLM(), FactoryEmbedder()
    cvs = {"python": CV, "java": CV_JAVA}
    texts = {stack: cv.as_text() for stack, cv in cvs.items()}
    run = pipeline.run(
        [
            lambda: pipeline.collect([FakeSource("a", [enrich(JAVA_JOB), enrich(PY_JOB)])], []),
            lambda: pipeline.screen(HardFilter(PREFS)),
            lambda: pipeline.embed_rank(factory, texts),
            lambda: pipeline.llm_score(llm, PROFILE, texts, top_n=5),
            lambda: pipeline.documents(llm, PROFILE, cvs, render, tmp_path, 70, 5),
        ]
    )
    assert run.status == "success", run.errors
    assert sorted(factory.calls) == sorted(texts.values()), "um embedder por perfil"
    assert llm.score_cv == {
        "Desenvolvedor Java Júnior": "java",
        "Desenvolvedor Python Pleno": "python",
    }
    with pipeline.sessions() as s:
        apps = {a.job.title: a.cv_variant_path for a in s.scalars(select(Application))}
    java_pdf = next(n for n in rendered if apps["Desenvolvedor Java Júnior"].endswith(n))
    assert rendered[java_pdf] == "Perfil Java e POO.", "PDF montado sobre o CV do perfil java"


def test_rescreen_brings_back_filtered_jobs(pipeline):
    from night_shift.adapters.storage.repository import JobRepository

    old_prefs = PREFS.model_copy(update={"blocked_keywords": ["java"]})
    pipeline.run(
        [
            lambda: pipeline.collect([FakeSource("a", [enrich(JAVA_JOB)])], []),
            lambda: pipeline.screen(HardFilter(old_prefs)),
        ]
    )
    with pipeline.sessions.begin() as s:
        assert s.scalars(select(Score)).one().filter_reason == "título bloqueado: java"
        assert JobRepository(s).reset_screening() == 1
    pipeline.run([lambda: pipeline.screen(HardFilter(PREFS))])
    with pipeline.sessions() as s:
        assert s.scalars(select(Score)).one().filter_reason is None


def test_queue_filter_by_stack(paths):
    db.upgrade(paths.db_url)
    engine = db.make_engine(paths.db_url)
    sessions = db.make_session_factory(engine)
    with sessions.begin() as s:
        for job in (enrich(JAVA_JOB), enrich(PY_JOB)):
            row = Job(
                source=job.source,
                external_id=job.external_id,
                company_name=job.company_name,
                title=job.title,
                description=job.description,
                url=job.url,
                content_hash=job.content_hash,
                stack=job.stack,
            )
            s.add(row)
            s.flush()
            s.add(Score(job_id=row.id, llm_score=60, embed_similarity=0.5, red_flags=[]))
    client = TestClient(create_app(sessions))
    java_only = client.get("/fila?view=manual&stack=java").text
    assert (
        "Desenvolvedor Java Júnior" in java_only and "Desenvolvedor Python Pleno" not in java_only
    )
    assert 'class="tag stack stack-java"' in java_only
    assert client.get("/fila?stack=cobol").status_code == 422
    engine.dispose()


def test_embed_rank_accepts_the_keyword_embedder_class(pipeline):
    from night_shift.application.keywords import KeywordEmbedder

    texts = {"python": CV.as_text(), "java": CV_JAVA.as_text() + " java spring poo"}
    run = pipeline.run(
        [
            lambda: pipeline.collect([FakeSource("a", [enrich(JAVA_JOB), enrich(PY_JOB)])], []),
            lambda: pipeline.screen(HardFilter(PREFS)),
            lambda: pipeline.embed_rank(KeywordEmbedder, texts),
        ]
    )
    assert run.status == "success", run.errors
    assert run.stats["embedded"] == 2
