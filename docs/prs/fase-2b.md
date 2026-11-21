## O que muda

Ajuste de escopo combinado em 21/11/2026, entre a Fase 2 e a Fase 3: **o Ollama sai do caminho
padrão** e a fila de revisão vira **duas filas**, uma automática e uma manual.

> PR empilhado sobre o #2 (`fase-2/painel`). Revise e mergeie o #2 primeiro; depois disso
> este PR passa a apontar para a `main`.

### 1. Claude sem chave de API

- Adapter novo `adapters/llm/claude_cli.py`: chama o **Claude Code CLI** em modo headless (`claude -p`) com o login da assinatura do usuário. O consumo entra nos limites do plano Pro.
- Cada chamada é isolada: `--tools ""` (sem ferramentas), `--strict-mcp-config`, `--no-session-persistence`, rodando numa pasta temporária vazia. O prompt vai pela entrada padrão (o limite de linha de comando do Windows é ~32 mil caracteres) e a resposta é forçada no schema com `--json-schema`.
- Sem login, limite de uso atingido ou executável ausente viram `LLMUnavailable`: a etapa para e o que já foi avaliado fica salvo. Outros erros só pulam aquela vaga.
- Modelo padrão: `haiku`. Configurável em `llm.claude_model`.
- `llm.provider: ollama` continua funcionando como antes.

### 2. Similaridade sem modelo

`application/keywords.py`: `KeywordEmbedder` implementa a porta `Embedder` com a frequência dos termos do próprio CV. Só decide a ordem em que as vagas vão para o LLM.

### 3. Limite de tempo

`--time-budget N` (ou `llm.time_budget_minutes`, padrão 120). Quando o tempo acaba, a etapa de nota para entre uma vaga e outra; as restantes contam como `llm_deferred` e ficam para a próxima execução.

### 4. Duas filas

`domain/lanes.py`:

- **Automática:** fonte de baixo risco (Greenhouse/Lever/Ashby) **e** nota ≥ `automation.auto_apply_min_score` (85) **e** nenhum red flag.
- **Manual:** todo o resto. O card mostra o motivo ("gupy: candidatura só manual", "nota abaixo de 85", "tem alertas").

A fila é calculada na hora, não gravada: mudar o limiar reclassifica tudo sem reprocessar. No painel, as abas viram **Manual**, **Automática**, Aplicadas e Descartadas. A aplicação automática em si é a Fase 5 (`night-shift apply`).

### 5. Prompt e `--rescore`

- O primeiro teste real mostrou o Haiku listando "salário não informado", "modelo não informado" e "tecnólogo" como red flags. Como qualquer red flag manda a vaga para a fila manual, **nada chegaria à automática**. O prompt agora define red flag como incompatibilidade concreta **exigida** pela vaga, com exemplos do que conta e do que não conta.
- `night-shift rank --rescore` apaga as notas de vagas sem decisão para reavaliar depois de mudar prompt ou modelo.

## Como foi testado

- [x] `uv run ruff check .` e `uv run ruff format --check .`
- [x] `uv run pytest`: 118 testes (21 novos). Adapter do CLI com o subprocess substituído e a saída no formato real (sucesso, `structured_output`, JSON entre crases, sem login, limite de uso, timeout, executável ausente, prompt pela entrada padrão). Palavras-chave, regras de fila, limite de tempo com relógio falso, abas e limiar no painel.
- [x] **Rodado de verdade com o Haiku**: `rank --top 5` levou ~50–60 s, cerca de 10 s por vaga; 2 h cobrem ~650 vagas. Antes do ajuste de prompt, todas as 5 vagas tinham red flags genéricos. Depois, a vaga de IA do BTG (nota 78) ficou sem red flags e as outras ficaram só com incompatibilidades reais (.NET/NestJS obrigatórios, Node.js, Java/Kafka/K8s, nível specialist).
- [x] Sem login, o `rank` falha com "Not logged in ... (rode `claude` uma vez no terminal e faça login)" e mantém a similaridade calculada.

## O que não foi coberto / riscos

- **Amostra pequena**: 5 vagas avaliadas de verdade. A calibragem do prompt merece um benchmark com ~20 vagas rotuladas (decisão em aberto no escopo).
- **Limites do plano Pro são compartilhados** com o uso normal do Claude; o tempo por execução não é o mesmo que o limite de uso. Se o limite acabar no meio da noite, a execução termina como `failed` com as notas parciais salvas.
- O `claude` instalado pelo winget só entra no PATH de terminais novos; o adapter também procura na pasta do winget.

## Migrations

Nenhuma.

🤖 Generated with [Claude Code](https://claude.com/claude-code)
