# night-shift

Sistema local que trabalha enquanto você dorme: coleta vagas, avalia o encaixe com seu perfil
usando embeddings e um LLM local, se candidata onde é seguro, deixa o resto numa fila para revisão
e rascunha e-mails de apresentação para empresas-alvo.

> Status: **Fase 1 (coleta + ranking)**. Veja o [escopo do MVP](docs/ESCOPO.md).

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

### LLM local

Instale o [Ollama](https://ollama.com) e baixe os modelos (cabem numa GPU de 8 GB):

```powershell
ollama pull qwen3:8b   # nota das vagas
ollama pull bge-m3     # embeddings (similaridade vaga x CV)
```

## Uso

```powershell
uv run night-shift run                 # coleta + filtro + similaridade + nota (pipeline da noite)
uv run night-shift collect             # só coleta e filtro (não precisa de Ollama)
uv run night-shift rank --top 10       # só similaridade + nota
uv run night-shift jobs -n 20          # melhores vagas avaliadas
uv run night-shift companies probe nubank stone   # descobre o ATS de uma empresa
```

## Desenvolvimento

```powershell
uv run pytest
uv run ruff check . ; uv run ruff format .
uv run alembic revision --autogenerate -m "descricao"   # após mudar models.py
```

## Stack

Python 3.13 · Typer · httpx · SQLAlchemy 2 · Alembic · Pydantic 2 · SQLite · Ollama ·
pywin32 (Job Object) · a seguir: FastAPI + HTMX, Playwright
