import pytest

from night_shift.application.keywords import KeywordEmbedder, tokenize
from night_shift.application.scoring import cosine
from night_shift.domain.enums import Source
from night_shift.domain.lanes import Lane, lane_for, manual_reason

CV = "Python FastAPI SQLAlchemy AWS Lambda SQS LLMs análise de crédito fintech Python"


def test_tokenize_folds_and_drops_stopwords():
    assert tokenize("Experiência com Python e FastAPI, CI/CD e C# .NET") == [
        "python",
        "fastapi",
        "ci",
        "cd",
        "c#",
        "net",
    ]


def test_similarity_prefers_matching_stack():
    emb = KeywordEmbedder(CV)
    cv_vec, python_job, java_job, empty = emb.embed(
        [
            CV,
            "Backend Python com FastAPI na AWS (Lambda, SQS) para crédito",
            "Backend Java com Spring e Kafka",
            "",
        ]
    )
    assert cosine(cv_vec, python_job) > cosine(cv_vec, java_job)
    assert cosine(cv_vec, empty) == 0.0


@pytest.mark.parametrize(
    ("source", "score", "flags", "lane"),
    [
        (Source.GREENHOUSE, 90, [], Lane.AUTO),
        (Source.ASHBY, 85, [], Lane.AUTO),
        (Source.LEVER, 84, [], Lane.MANUAL),
        (Source.GREENHOUSE, 95, ["exige inglês fluente"], Lane.MANUAL),
        (Source.GUPY, 99, [], Lane.MANUAL),
        (Source.LINKEDIN_ALERTS, 99, [], Lane.MANUAL),
        (Source.GREENHOUSE, None, [], Lane.MANUAL),
    ],
)
def test_lane_for(source, score, flags, lane):
    assert lane_for(source, score, flags, threshold=85) is lane


def test_manual_reason_explains_first_blocker():
    assert "gupy" in manual_reason(Source.GUPY, 99, [], 85)
    assert manual_reason(Source.LEVER, 60, [], 85) == "nota abaixo de 85"
    assert manual_reason(Source.LEVER, 90, ["x"], 85) == "tem alertas"
