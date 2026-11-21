# night-shift

Sistema local que trabalha enquanto você dorme: coleta vagas, avalia o encaixe com seu perfil
usando embeddings e um LLM local, se candidata onde é seguro, deixa o resto numa fila para revisão
e rascunha e-mails de apresentação para empresas-alvo.

> Status: planejamento. Veja o [escopo do MVP](docs/ESCOPO.md).

## Ideia em uma linha

`02:00` coleta → filtra → ranqueia → ajusta CV → aplica ou enfileira → rascunha outreach → `08:00` você revisa no painel.

## Stack

Python 3.12 · FastAPI · SQLAlchemy · Pydantic · SQLite · Playwright · Ollama · HTMX
