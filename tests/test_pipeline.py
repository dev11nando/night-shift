"""Pipeline ponta a ponta no SQLite, com fontes, embedder e LLM falsos."""

import pytest
from sqlalchemy import func, select

from night_shift.adapters.storage import db
from night_shift.adapters.storage.models import Job, Run, Score
from night_shift.application.pipeline import Pipeline
from night_shift.application.scoring import JobFit
from night_shift.config import CompanyConfig, Preferences, Profile
from night_shift.domain.enums import Level, RunStatus
from night_shift.domain.filters import HardFilter
from night_shift.ports import LLMUnavailable, SourceError
from night_shift.runtime.stop_flag import StopFlag
from tests.factories import posting

VOCAB = ["python", "fastapi", "aws", "java", "llm"]
CV_TEXT = "python fastapi aws llm"


class FakeSource:
    def __init__(self, name, postings, fail=False):
        self.name, self.postings, self.fail = name, postings, fail

    def fetch(self):
        if self.fail:
            raise SourceError("fora do ar")
        return iter(self.postings)


class BagOfWordsEmbedder:
    model = "bow"

    def embed(self, texts):
        return [[float(w in t.casefold()) for w in VOCAB] for t in texts]


class FakeLLM:
    model = "fake"

    def __init__(self, fail_on=None, unavailable=False):
        self.calls, self.fail_on, self.unavailable = [], fail_on, unavailable

    def complete_json(self, system, prompt, schema):
        if self.unavailable:
            raise LLMUnavailable("ollama fora do ar")
        job_part = prompt.split("## Vaga")[1].split("## Como pontuar")[0]
        self.calls.append(job_part)
        if self.fail_on and self.fail_on in job_part:
            raise ValueError("resposta quebrada")
        score = 90 if "fastapi" in job_part.casefold() else 40
        return JobFit(score=score, rationale="ok", red_flags=[])


PROFILE = Profile(
    name="Eu",
    email="eu@x.com",
    preferences=Preferences(levels=[Level.PLENO, Level.JUNIOR], keywords=["python", "java"]),
)

GOOD = posting(external_id="1", title="Backend Python Pleno", description="python fastapi aws")
OK = posting(external_id="2", title="Desenvolvedor Python", description="python django")
SENIOR = posting(external_id="3", title="Senior Python Engineer", description="python")
OFF = posting(external_id="4", title="Desenvolvedor Java", description="java spring")


@pytest.fixture
def pipeline(paths):
    db.upgrade(paths.db_url)
    engine = db.make_engine(paths.db_url)
    p = Pipeline(db.make_session_factory(engine), StopFlag(paths.run_dir), log=lambda _: None)
    yield p
    engine.dispose()


def full_run(p, sources, llm, top_n=10):
    return p.run(
        [
            lambda: p.collect(sources, [CompanyConfig(name="Fintech X")]),
            lambda: p.screen(HardFilter(PROFILE.preferences)),
            lambda: p.embed_rank(BagOfWordsEmbedder(), CV_TEXT),
            lambda: p.llm_score(llm, PROFILE, CV_TEXT, top_n),
        ]
    )


def scores(p):
    with p.sessions() as s:
        return {
            sc.job.external_id: (sc.filter_reason, sc.embed_similarity, sc.llm_score)
            for sc in s.scalars(select(Score))
        }


def test_full_run_filters_ranks_and_scores(pipeline):
    run = full_run(pipeline, [FakeSource("a", [GOOD, OK, SENIOR, OFF])], FakeLLM())

    assert run.status is RunStatus.SUCCESS
    assert run.stats == {
        "collected": 4,
        "new": 4,
        "passed_filter": 3,
        "filtered_out": 1,
        "embedded": 3,
        "llm_scored": 3,
    }
    result = scores(pipeline)
    assert "nível senior" in result["3"][0]
    assert result["1"][1] > result["2"][1], "vaga com fastapi+aws deve ser mais parecida com o CV"
    assert result["1"][2] == 90
    assert result["4"][2] == 40, "java passou no filtro (keyword) mas o LLM dá nota baixa"


def test_second_run_is_idempotent(pipeline):
    llm = FakeLLM()
    full_run(pipeline, [FakeSource("a", [GOOD, OK])], llm)
    run2 = full_run(pipeline, [FakeSource("a", [GOOD, OK])], llm)

    assert run2.stats == {"collected": 2, "new": 0}
    assert len(llm.calls) == 2
    with pipeline.sessions() as s:
        assert s.scalar(select(func.count(Job.id))) == 2


def test_same_job_in_two_sources_is_stored_once(pipeline):
    from dataclasses import replace

    from night_shift.domain.enums import Source

    copy = replace(GOOD, source=Source.GUPY, external_id="gupy-99")
    run = full_run(pipeline, [FakeSource("a", [GOOD]), FakeSource("b", [copy])], FakeLLM())
    assert run.stats["new"] == 1


def test_top_n_limits_llm_calls_and_leftovers_wait(pipeline):
    llm = FakeLLM()
    full_run(pipeline, [FakeSource("a", [GOOD, OK, OFF])], llm, top_n=1)

    assert len(llm.calls) == 1
    assert "fastapi" in llm.calls[0], "o mais parecido com o CV vai primeiro"
    pipeline.stats.clear()
    pipeline.llm_score(llm, PROFILE, CV_TEXT, top_n=5)
    assert len(llm.calls) == 3, "sobras da noite anterior são avaliadas depois"


def test_broken_source_does_not_stop_others(pipeline):
    run = full_run(
        pipeline, [FakeSource("quebrada", [], fail=True), FakeSource("ok", [GOOD])], FakeLLM()
    )
    assert run.status is RunStatus.SUCCESS
    assert run.stats["new"] == 1
    assert run.errors == ["quebrada: fora do ar"]


def test_one_bad_llm_answer_does_not_stop_others(pipeline):
    run = full_run(pipeline, [FakeSource("a", [GOOD, OK])], FakeLLM(fail_on="django"))
    assert run.stats["llm_scored"] == 1
    assert any("resposta quebrada" in e for e in run.errors)


def test_llm_unavailable_fails_run_but_keeps_collected_jobs(pipeline):
    run = full_run(pipeline, [FakeSource("a", [GOOD])], FakeLLM(unavailable=True))

    assert run.status is RunStatus.FAILED
    assert run.errors == ["ollama fora do ar"]
    assert scores(pipeline)["1"][1] is not None, "similaridade já gravada continua lá"


def test_time_budget_defers_remaining_jobs(pipeline):
    ticks = iter([0, 10, 70, 130])  # início; antes da 1ª vaga; antes da 2ª; antes da 3ª
    pipeline.clock = lambda: next(ticks)
    llm = FakeLLM()
    pipeline.run(
        [
            lambda: pipeline.collect([FakeSource("a", [GOOD, OK, OFF])], []),
            lambda: pipeline.screen(HardFilter(PROFILE.preferences)),
            lambda: pipeline.embed_rank(BagOfWordsEmbedder(), CV_TEXT),
            lambda: pipeline.llm_score(llm, PROFILE, CV_TEXT, top_n=10, budget_seconds=100),
        ]
    )

    assert len(llm.calls) == 2
    assert pipeline.stats["llm_deferred"] == 1
    assert pipeline.stats["llm_scored"] == 2


def test_stop_flag_halts_between_steps(pipeline):
    pipeline.stop.request()
    run = full_run(pipeline, [FakeSource("a", [GOOD])], FakeLLM())

    assert run.status is RunStatus.STOPPED
    with pipeline.sessions() as s:
        assert s.scalar(select(func.count(Job.id))) == 0
        assert s.scalars(select(Run)).one().finished_at is not None


def test_interrupted_run_is_marked_and_next_run_continues(pipeline):
    with pipeline.sessions.begin() as s:
        s.add(Run(stats={}, errors=[]))  # ficou "running": o processo morreu no meio

    run = full_run(pipeline, [FakeSource("a", [GOOD])], FakeLLM())

    assert run.status is RunStatus.SUCCESS
    with pipeline.sessions() as s:
        first = s.scalars(select(Run).order_by(Run.id)).first()
        assert first.status is RunStatus.FAILED
        assert "interrompida" in first.errors[-1]


def test_progress_is_written_while_running(pipeline):
    seen = {}

    def peek():
        with pipeline.sessions() as s:
            run = s.get(Run, pipeline.run_id)
            seen.update(stage=run.stage, stats=dict(run.stats), log=run.log_path)

    pipeline.log_path = "logs/x.log"
    run = pipeline.run(
        [
            lambda: pipeline.collect([FakeSource("a", [GOOD, OK])], []),
            lambda: pipeline.screen(HardFilter(PROFILE.preferences)),
            peek,
            lambda: pipeline.llm_score(FakeLLM(), PROFILE, CV_TEXT, 5, budget_seconds=600),
        ]
    )
    assert seen["stage"] == "filtro" and seen["stats"]["collected"] == 2
    assert seen["log"] == "logs/x.log"
    with pipeline.sessions() as s:
        final = s.get(Run, run.id)
        assert final.stage == "nota" and final.current_item is None
        assert final.budget_ends_at is not None
    assert pipeline.run_id is None
