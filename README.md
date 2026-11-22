# night-shift

Sistema local que trabalha enquanto você dorme: coleta vagas, avalia o encaixe com seu perfil
usando um LLM (Claude Haiku pela sua assinatura, ou Ollama local), prepara CV ajustado e carta
para as melhores, separa o que dá para aplicar sozinho do que precisa de você e rascunha e-mails
de apresentação para empresas-alvo.

> Status: **Fase 8 (perfis de CV por stack)**. Veja o [escopo do MVP](docs/ESCOPO.md).

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
uv run night-shift serve --open        # painel em http://127.0.0.1:8765 (Hoje, Ao vivo, Fila, Mercado)
uv run night-shift jobs -n 20          # melhores vagas avaliadas, no terminal
uv run night-shift db enrich           # extrai nível/contrato/salário de vagas antigas
uv run night-shift companies probe nubank stone   # descobre o ATS de uma empresa
```

### Currículo (perfis por stack)

```powershell
uv run night-shift cv check            # confere cada perfil e a versão em inglês
uv run night-shift cv pdf              # output/cv/curriculo-<perfil>.pdf e resume-<perfil>-en.pdf
uv run night-shift rank --rescreen     # reclassifica a stack das vagas e refaz o filtro
```

Três perfis de CV, cada um com versão em inglês e sempre em **uma página**:

| Perfil | Arquivo | Níveis aceitos |
|---|---|---|
| Python backend | `config/cv_master.yaml` | júnior e pleno |
| IA / LLM | `config/cv_ia.yaml` | júnior e pleno |
| Java (foco em POO) | `config/cv_java.yaml` | só júnior |

Cada vaga é classificada numa stack pelo título (e, sem pista no título, pela descrição); a
nota, o CV ajustado e a carta usam o perfil dela. Níveis por stack em
`preferences.stack_levels` do `profile.yaml`. Vaga em inglês recebe CV e carta em inglês.

### Acompanhar uma rodada

No topo de todas as páginas do painel há **Buscar vagas** (dispara uma busca na hora, mesmo
com a busca automática desligada) e **Desligar** (encerra tudo). A página **Ao vivo** mostra a
execução em andamento: etapa, vaga atual, contadores, notas saindo, log e tempo restante do
limite de LLM, atualizando a cada 2 s, com botão **Parar**.

```powershell
uv run night-shift schedule disable    # desliga só a busca automática diária
uv run night-shift schedule enable     # religa
```

### Outreach (empresas sem vaga)

```powershell
uv run night-shift outreach -n 10     # acha contatos públicos e escreve as mensagens
```

A aba **Outreach** do painel mostra, por empresa, a nota de conexão do LinkedIn e o e-mail
prontos, o link para achar recrutadores no LinkedIn e a página de carreiras. Você envia
(LinkedIn ou "Abrir no Gmail") e marca como enviada. Também roda na busca de cada noite.

### Funil

A aba **Funil** mostra suas candidaturas da aplicação até a proposta, com a % de passagem
entre as etapas (no total e por fonte). Mova cada card conforme o processo anda (teve
resposta, entrevista, proposta, recusada) e anote o que aconteceu direto no card.

### Aplicar (assistido)

```powershell
uv run night-shift apply               # abre as vagas da fila automática já preenchidas
uv run night-shift apply --job 589     # uma vaga específica (Greenhouse/Lever/Ashby)
uv run night-shift apply --preview     # só preenche e tira print, sem enviar
```

O sistema preenche dados, CV ajustado e carta; **você confere, completa e clica em enviar**.
Ele nunca envia sozinho e nunca preenche CPF, raça, gênero, orientação ou deficiência.
Configure `application.current_company` e `application.answers` no `profile.yaml` e o
LinkedIn em `contact.linkedin` do `cv_master.yaml` para sobrar menos campo para você.

### Rodar sozinho toda noite

```powershell
uv run night-shift schedule install --at 00:30 --max-minutes 30   # janela 00:30–01:00
uv run night-shift schedule status               # "todo dia às 02:00"
uv run night-shift schedule run-now              # dispara agora, pelo mesmo caminho da noite
uv run night-shift off                           # desliga TUDO (pipeline, painel, tarefa)
uv run night-shift on                            # religa
uv run night-shift shortcuts                     # atalhos OFF / ON / Painel na área de trabalho
```

Cada execução grava um log em `logs/`. O PC precisa estar ligado (pode estar suspenso: a
tarefa acorda o PC) e com você logado.

## Desenvolvimento

```powershell
uv run pytest
uv run ruff check . ; uv run ruff format .
uv run alembic revision --autogenerate -m "descricao"   # após mudar models.py
```

## Stack

Python 3.13 · Typer · httpx · SQLAlchemy 2 · Alembic · Pydantic 2 · SQLite · Claude Code CLI · fpdf2 ·
FastAPI + Jinja2 + HTMX · Playwright · pywin32 (Job Object)
