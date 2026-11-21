import pytest

from night_shift.domain.enums import Level, WorkModel
from night_shift.domain.text import contains_term, fold, infer_level, infer_work_model


def test_fold_removes_case_and_accents():
    assert fold("Sênior Júnior HÍBRIDO") == "senior junior hibrido"


@pytest.mark.parametrize(
    ("text", "term", "expected"),
    [
        ("Back-end Python", "python", True),
        ("Desenvolvedor JavaScript", "java", False),
        ("Engenheiro(a) de Software", "engenheiro", True),
        ("Estágio em TI", "estagio", True),
        ("Vaga .NET Core", ".net", True),
        ("Backend Engineer", "back-end", False),
    ],
)
def test_contains_term_matches_whole_words(text, term, expected):
    assert contains_term(text, term) is expected


@pytest.mark.parametrize(
    ("title", "level"),
    [
        ("Desenvolvedor Python Pleno", Level.PLENO),
        ("Software Engineer II", Level.PLENO),
        ("Engenheiro de Software Sr.", Level.SENIOR),
        ("Backend Developer Pleno/Sênior", Level.PLENO),
        ("Desenvolvedor Júnior/Pleno", Level.JUNIOR),
        ("Staff Engineer", Level.SENIOR),
        ("Tech Lead Backend", Level.SENIOR),
        ("Desenvolvedor Júnior", Level.JUNIOR),
        ("Software Engineer I", Level.JUNIOR),
        ("Backend Engineer", None),
    ],
)
def test_infer_level(title, level):
    assert infer_level(title) is level


@pytest.mark.parametrize(
    ("texts", "model"),
    [
        (("Brazil (Remote)",), WorkModel.REMOTO),
        (("São Paulo - Híbrido",), WorkModel.HIBRIDO),
        (("Remote or hybrid",), WorkModel.HIBRIDO),
        (("Presencial em Campinas",), WorkModel.PRESENCIAL),
        (("São Paulo, SP", None), None),
    ],
)
def test_infer_work_model(texts, model):
    assert infer_work_model(*texts) is model
