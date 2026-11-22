## O que muda

`night-shift schedule install` passa a receber o limite de duração da tarefa em **minutos**
(`--max-minutes`, padrão 180) no lugar de horas (`--max-hours`). Com isso dá para definir uma
janela exata, como **00:30 até 01:00**:

```powershell
uv run night-shift schedule install --at 00:30 --max-minutes 30
```

O `--max-minutes` é a trava do Windows (encerra a tarefa no limite). Para a rodada terminar
limpa antes disso, o `llm.time_budget_minutes` do `profile.yaml` (25 na configuração local)
faz as etapas de LLM pararem sozinhas.

## Como foi testado

- [x] `uv run ruff check .`, `uv run pytest` (XML da tarefa com `PT30M`).
- [x] A tarefa real foi instalada às 00:30 (com o limite antigo de 1 h, porque faltavam 5 min) e reinstalada com `--max-minutes 30` depois da primeira rodada.

## Migrations

Nenhuma.

🤖 Generated with [Claude Code](https://claude.com/claude-code)
