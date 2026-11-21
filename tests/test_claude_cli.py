"""Adapter do Claude Code CLI com o subprocess substituído (formato real da saída
``--output-format json`` conferido em 21/11/2026)."""

import json
import subprocess

import pytest

from night_shift.adapters.llm import claude_cli
from night_shift.adapters.llm.claude_cli import ClaudeCLI, ClaudeCLIError
from night_shift.application.scoring import JobFit
from night_shift.ports import LLMUnavailable


@pytest.fixture(autouse=True)
def fake_executable(monkeypatch):
    monkeypatch.setattr(claude_cli, "find_executable", lambda _: "C:/bin/claude.exe")


def result(**fields) -> str:
    base = {"type": "result", "subtype": "success", "is_error": False, "num_turns": 1}
    return json.dumps(base | fields)


def runner_returning(stdout: str, calls: list | None = None, returncode: int = 0):
    def run(args, stdin, cwd, timeout):
        if calls is not None:
            calls.append({"args": args, "stdin": stdin, "cwd": cwd})
        return subprocess.CompletedProcess(args, returncode, stdout=stdout, stderr="")

    return run


def test_sends_isolated_headless_call_with_schema():
    calls = []
    out = result(structured_output={"score": 77, "rationale": "Boa stack.", "red_flags": []})
    fit = ClaudeCLI("haiku", runner=runner_returning(out, calls)).complete_json(
        "sistema", "prompt longo", JobFit
    )

    assert fit.score == 77
    args = calls[0]["args"]
    assert args[:2] == ["C:/bin/claude.exe", "-p"]
    assert args[args.index("--model") + 1] == "haiku"
    assert args[args.index("--tools") + 1] == "", "sem ferramentas"
    assert "--no-session-persistence" in args and "--strict-mcp-config" in args
    assert json.loads(args[args.index("--json-schema") + 1])["properties"]["score"]
    assert calls[0]["stdin"] == "prompt longo", "prompt vai pela entrada padrão"
    assert "prompt longo" not in args


def test_falls_back_to_result_text_with_fences():
    out = result(result='```json\n{"score": 40, "rationale": "Java."}\n```')
    fit = ClaudeCLI(runner=runner_returning(out)).complete_json("s", "p", JobFit)
    assert (fit.score, fit.red_flags) == (40, [])


def test_not_logged_in_is_unavailable_with_hint():
    out = result(is_error=True, result="Not logged in · Please run /login")
    with pytest.raises(LLMUnavailable, match="faça login"):
        ClaudeCLI(runner=runner_returning(out, returncode=1)).complete_json("s", "p", JobFit)


def test_usage_limit_is_unavailable():
    out = result(is_error=True, result="Claude usage limit reached. Resets at 3am.")
    with pytest.raises(LLMUnavailable, match="usage limit"):
        ClaudeCLI(runner=runner_returning(out)).complete_json("s", "p", JobFit)


def test_other_errors_affect_only_this_job():
    out = result(is_error=True, result="algo inesperado")
    with pytest.raises(ClaudeCLIError):
        ClaudeCLI(runner=runner_returning(out)).complete_json("s", "p", JobFit)


def test_out_of_schema_is_error():
    out = result(structured_output={"score": 500, "rationale": "x"})
    with pytest.raises(ClaudeCLIError, match="fora do schema"):
        ClaudeCLI(runner=runner_returning(out)).complete_json("s", "p", JobFit)


def test_timeout_is_error():
    def slow(args, stdin, cwd, timeout):
        raise subprocess.TimeoutExpired(args, timeout)

    with pytest.raises(ClaudeCLIError, match="sem resposta"):
        ClaudeCLI(runner=slow, timeout=5).complete_json("s", "p", JobFit)


def test_missing_executable_is_unavailable(monkeypatch):
    monkeypatch.setattr(claude_cli, "find_executable", lambda _: None)
    with pytest.raises(LLMUnavailable, match="winget install"):
        ClaudeCLI().complete_json("s", "p", JobFit)
