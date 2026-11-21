# night-shift

Sistema local que trabalha enquanto você dorme: coleta vagas, avalia o encaixe com seu perfil
usando um LLM (Claude Haiku pela sua assinatura, ou Ollama local), prepara CV ajustado e carta
para as melhores, separa o que dá para aplicar sozinho do que precisa de você e rascunha e-mails
de apresentação para empresas-alvo.

> Status: **Fase 3 (CV ajustado e carta)**. Veja o [escopo do MVP](docs/ESCOPO.md).

## Ideia em uma linha

`02:00` coleta → filtra → ranqueia → ajusta CV → aplica ou enfileira → rascunha outreach → `08:00` você revisa no painel.

## Setup (Windows)

Pré-requisito: [uv](https://docs.astral.sh/uv/) no PATH.

```powershell
uv sync                 # cria .venv com o Python gerenciado pelo uv e instala tudo
uv run night-shift init # cria config/*.yaml a partir dos exemplos + banco SQLite
uv run night-shift doctor
```

Depois do `init`, preencha `config/profile.yaml`, `config/cv_master.yaml` e `config/companies.yaml`.
Esses arquivos ficam **fora do git**.

> **Não use o Python da Microsoft Store** nem `python -m uv` (que força o Python de quem chamou).
> O Python da Store roda num pacote AppX que deixa os processos filhos escaparem do Job Object,
> e aí o `night-shift off` não consegue garantir que nada fique rodando. O projeto já fixa
> `python-preference = "only-managed"` e o `doctor` acusa se a venv estiver no Python errado.

### LLM

Padrão (`llm.provider: claude`): Claude Haiku pelo **Claude Code CLI**, com o login da sua
assinatura, sem chave de API. O consumo entra nos limites do seu plano.

```powershell
winget install Anthropic.ClaudeCode
claude          # num terminal novo: faça login com a conta da assinatura e saia com /exit
```

Alternativa local (`llm.provider: ollama`): instale o [Ollama](https://ollama.com) e rode
`ollama pull qwen3:8b` e `ollama pull bge-m3`.

## Uso

```powershell
uv run night-shift run                 # coleta + filtro + similaridade + nota (pipeline da noite)
uv run night-shift run --time-budget 120   # nota por no máximo 120 min; o resto fica p/ depois
uv run night-shift collect             # só coleta e filtro (não precisa de LLM)
uv run night-shift rank --top 10       # só similaridade + nota
uv run night-shift rank --rescore      # reavalia vagas sem decisão (ex.: depois de mudar o prompt)
uv run night-shift docs -n 5          # CV ajustado (output/cv/*.pdf) + carta para as melhores
uv run night-shift docs --regenerate   # gera de novo para as vagas da fila (ex.: mudou o CV)
uv run night-shift serve --open        # painel em http://127.0.0.1:8765 (Hoje, Fila, Mercado)
uv run night-shift jobs -n 20          # melhores vagas avaliadas, no terminal
uv run night-shift db enrich           # extrai nível/contrato/salário de vagas antigas
uv run night-shift companies probe nubank stone   # descobre o ATS de uma empresa
```

## Desenvolvimento

```powershell
uv run pytest
uv run ruff check . ; uv run ruff format .
uv run alembic revision --autogenerate -m "descricao"   # após mudar models.py
```

## Stack

Python 3.13 · Typer · httpx · SQLAlchemy 2 · Alembic · Pydantic 2 · SQLite · Claude Code CLI · fpdf2 ·
FastAPI + Jinja2 + HTMX · pywin32 (Job Object) · a seguir: Playwright
