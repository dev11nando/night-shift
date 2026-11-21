"""Claude via Claude Code CLI em modo headless (``claude -p``).

Usa o login da assinatura (plano Pro/Max) do usuário, sem chave de API. Cada chamada é
isolada: sem ferramentas, sem MCP, sem salvar sessão, rodando numa pasta vazia para não
carregar CLAUDE.md nem configurações do projeto.
"""

import json
import re
import shutil
import subprocess
import tempfile
from collections.abc import Callable
from pathlib import Path

from pydantic import BaseModel, ValidationError

from night_shift.ports import LLMUnavailable

DEFAULT_EXECUTABLE = "claude"

# Mensagens que significam "não adianta tentar a próxima vaga agora".
_FATAL_PATTERNS = re.compile(
    r"not logged in|/login|invalid api key|usage limit|rate limit|limit reached|"
    r"credit balance|overloaded|authentication",
    re.IGNORECASE,
)

Runner = Callable[[list[str], str, Path, float], subprocess.CompletedProcess]


class ClaudeCLIError(Exception):
    pass


def _run(args: list[str], stdin: str, cwd: Path, timeout: float) -> subprocess.CompletedProcess:
    # O prompt vai pela entrada padrão: a linha de comando do Windows tem limite de ~32 mil
    # caracteres, e CV + descrição da vaga podem chegar perto disso.
    return subprocess.run(
        args,
        input=stdin,
        cwd=cwd,
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=timeout,
    )


def find_executable(configured: str = DEFAULT_EXECUTABLE) -> str | None:
    """Procura o ``claude`` no PATH ou na pasta onde o winget instala."""
    found = shutil.which(configured)
    if found:
        return found
    winget = Path.home() / "AppData/Local/Microsoft/WinGet/Packages"
    for candidate in winget.glob("Anthropic.ClaudeCode_*/claude.exe"):
        return str(candidate)
    return None


def _extract_json(text: str) -> str:
    """Tira cercas de markdown que o modelo às vezes coloca em volta do JSON."""
    m = re.search(r"\{.*\}", text, re.DOTALL)
    return m.group(0) if m else text


class ClaudeCLI:
    def __init__(
        self,
        model: str = "haiku",
        *,
        executable: str = DEFAULT_EXECUTABLE,
        timeout: float = 180.0,
        runner: Runner = _run,
    ) -> None:
        self.model = f"claude:{model}"
        self._model = model
        self._executable = executable
        self._timeout = timeout
        self._runner = runner
        self._workdir = Path(tempfile.mkdtemp(prefix="night-shift-claude-"))

    def _args(self, exe: str, system: str, schema: dict) -> list[str]:
        return [
            exe,
            "-p",
            "--model",
            self._model,
            "--system-prompt",
            system,
            "--output-format",
            "json",
            "--json-schema",
            json.dumps(schema),
            "--tools",
            "",
            "--strict-mcp-config",
            "--no-session-persistence",
        ]

    def complete_json[T: BaseModel](self, system: str, prompt: str, schema: type[T]) -> T:
        exe = find_executable(self._executable)
        if exe is None:
            raise LLMUnavailable(
                "Claude Code CLI não encontrado; instale com `winget install Anthropic.ClaudeCode`"
            )
        try:
            proc = self._runner(
                self._args(exe, system, schema.model_json_schema()),
                prompt,
                self._workdir,
                self._timeout,
            )
        except subprocess.TimeoutExpired as e:
            raise ClaudeCLIError(f"sem resposta em {self._timeout:.0f}s") from e

        try:
            out = json.loads(proc.stdout)
        except ValueError as e:
            detail = (proc.stderr or proc.stdout).strip()[:300]
            if _FATAL_PATTERNS.search(detail):
                raise LLMUnavailable(f"Claude CLI: {detail}") from e
            raise ClaudeCLIError(f"saída não é JSON (exit {proc.returncode}): {detail}") from e

        if out.get("is_error"):
            detail = str(out.get("result") or out.get("terminal_reason") or "erro desconhecido")
            if _FATAL_PATTERNS.search(detail):
                hint = (
                    " (rode `claude` uma vez no terminal e faça login)" if "login" in detail else ""
                )
                raise LLMUnavailable(f"Claude CLI: {detail}{hint}")
            raise ClaudeCLIError(detail[:300])

        payload = out.get("structured_output")
        try:
            if payload is not None:
                return schema.model_validate(payload)
            return schema.model_validate_json(_extract_json(str(out.get("result", ""))))
        except ValidationError as e:
            raise ClaudeCLIError(f"resposta fora do schema: {str(out.get('result'))[:300]}") from e
