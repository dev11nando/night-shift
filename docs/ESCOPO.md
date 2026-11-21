# night-shift — Escopo do MVP

> Sistema local que trabalha enquanto eu durmo: busca vagas, avalia o encaixe com meu perfil,
> se candidata onde é seguro, prepara o resto para eu revisar de manhã e rascunha e-mails
> para empresas-alvo mesmo sem vaga aberta.

Status: **planejamento** · Última revisão: 21/11/2026

---

## 1. Objetivos

1. **Volume com qualidade:** cobrir mais vagas do que eu conseguiria manualmente, sem mandar candidatura ruim.
2. **Revisão rápida de manhã:** no máximo ~10 min por dia no painel para aprovar, aplicar e descartar.
3. **Outreach ativo:** rascunhos de cold e-mail personalizados para empresas com stack parecida, enviados por mim.
4. **Custo zero ou quase zero:** sem API paga. Modelo local + plano Claude Pro.
5. **Dados próprios de mercado:** guardar as faixas salariais publicadas para calibrar minha pretensão.

### Fora do escopo (por enquanto)

- Auto-apply no LinkedIn (risco de banimento: **nunca** automatizar).
- Envio automático de e-mails (só rascunhos; quem envia sou eu).
- Responder recrutador ou agendar entrevista.
- Rodar na nuvem. Roda local, no meu PC.

---

## 2. Perfil-alvo

| Critério | Valor |
|---|---|
| Cargo | Backend / Engenheiro de Software (Python), também "IA/LLM engineer" |
| Nível | Pleno (prioridade) e Júnior (peso menor) |
| Modelo | Remoto, híbrido ou presencial (Grande SP) |
| Contrato | CLT ou PJ |
| Stack-chave | Python, FastAPI, SQLAlchemy, Pydantic, AWS (Lambda, SQS, DynamoDB, S3), LLMs, mensageria, Docker |
| Setores bônus | Fintech, bancos digitais, fundos/gestoras, empresas de IA |

**Pretensão salarial:** fica em `config/profile.yaml` (**gitignored**), não no repositório. Regra usada no score:
PJ equivalente ≈ CLT bruto × 1,45 (cobre 13º, férias + 1/3, FGTS, benefícios e impostos/contador do Simples Nacional, Anexo III com Fator R).
Programador **não pode ser MEI**: PJ exige abrir ME.

---

## 3. Arquitetura

Hexagonal (ports & adapters), igual ao que uso no trabalho. O domínio não conhece Gupy, Ollama nem SQLite.

```
                 ┌──────────────── domain ────────────────┐
 JobSource  ───► │ Job, Company, Application, Score,       │ ◄─── LLMProvider
 (adapters)      │ OutreachDraft, CVVariant                │      (ollama | claude-cli)
                 │                                         │
 Applier    ◄─── │ use cases: collect, filter, rank,       │ ───► Notifier / Repository
 (adapters)      │ tailor_cv, apply_or_queue, outreach     │      (sqlite)
                 └─────────────────────────────────────────┘
```

### Portas

| Porta | Responsabilidade | Adapters previstos |
|---|---|---|
| `JobSource` | Listar vagas novas | Greenhouse, Lever, Ashby, Gupy, Programathor, alertas do LinkedIn via Gmail |
| `Embedder` | Vetorizar vaga e CV | Ollama (`bge-m3`, multilíngue) na GPU, sem precisar de torch |
| `LLMProvider` | Nota final, respostas e textos | Ollama (local), Claude Code headless (`claude -p`) |
| `Applier` | Submeter candidatura | Formulários Greenhouse/Lever/Ashby (Playwright); demais = fila |
| `CVRenderer` | Gerar PDF do CV ajustado | HTML + WeasyPrint (ou Typst) |
| `MailDrafts` | Criar rascunhos | Gmail API (só `drafts.create`, sem permissão de envio) |
| `Repository` | Persistência | SQLite via SQLAlchemy |

---

## 4. Fontes e risco

| Fonte | Coleta | Aplicação | Risco | Ação |
|---|---|---|---|---|
| Greenhouse / Lever / Ashby | API pública do job board da empresa | Formulário padrão | **Baixo** | Auto-apply se score ≥ limiar |
| Programathor | Página/listagem pública | Simples, mas com login | **Médio** | Fila (auto depois, se estável) |
| Gupy | `__NEXT_DATA__` da busca do portal (a API antiga dá 404); ~12 vagas por termo | Login + perguntas por vaga | **Médio** | Fila, com respostas pré-preenchidas |
| LinkedIn | E-mails de alerta no Gmail (não toca no site) | — | **Alto** | Só fila |
| GeekHunter | — | Modelo invertido (empresa procura) | — | Lembrete para manter o perfil |

Greenhouse/Lever/Ashby precisam do *slug* de cada empresa. Por isso, a **lista de empresas-alvo** (`config/companies.yaml`) serve tanto para a coleta quanto para o outreach.

---

## 5. Pipeline noturno

Agendado pelo Agendador de Tarefas do Windows (ex.: 02:00). Cada etapa é idempotente e registra execução.

```
1. collect      → centenas de vagas, dedupe por (fonte, id_externo) e hash do texto
2. hard_filter  → regras: stack, nível, local, palavras proibidas, já visto      (custo 0)
3. embed_rank   → similaridade vaga × CV mestre, corta no top ~30                 (palavras-chave, custo 0)
4. llm_score    → LLM dá nota 0–100 + justificativa curta + red flags              (Claude Haiku, limite de tempo)
5. tailor       → seleciona/reordena bullets do CV mestre e gera o PDF            (Ollama)
6. letter       → carta curta para score alto                                    (Claude, poucos/dia)
7. apply_or_queue → baixo risco + score ≥ limiar ⇒ aplica; senão ⇒ fila
8. outreach     → N empresas/dia sem contato recente ⇒ rascunho no Gmail          (Claude)
9. report       → resumo da noite no painel
```

### Orçamento de LLM

**Decisão de 21/11/2026 (experimental): Ollama fica de fora.** A nota das vagas usa o
**Claude Haiku via Claude Code CLI** (`claude -p`), com o login da assinatura Pro, sem chave
de API, com um limite de tempo por execução (padrão 120 min). A etapa 3 usa similaridade por
palavras-chave do CV em vez de embeddings. Medido: cerca de 10 s por vaga, então 2 h cobrem
cerca de 650 vagas, folga grande para as ~60 que passam no filtro por noite.

- **Claude (plano Pro):** etapas 4–6 e 8. O consumo entra nos limites do plano; se o limite
  acabar, a etapa para e o que já foi avaliado fica salvo.
- **Local (Ollama):** continua disponível com `llm.provider: ollama` (qwen3:8b + bge-m3 em
  GPU de 8 GB).
- O `LLMProvider` é trocável por config, sem mexer no pipeline.

### Duas filas

Cada vaga avaliada cai numa fila, calculada na hora (mudar o limiar reclassifica tudo):

- **Automática:** fonte de baixo risco (Greenhouse, Lever, Ashby) **e** nota ≥
  `automation.auto_apply_min_score` (85) **e** nenhum red flag. Aplicada depois pelo
  `night-shift apply` (Fase 5), que você dispara quando quiser.
- **Manual:** todo o resto, com o motivo exibido no painel.

---

## 6. CV mestre (sem inventar)

`config/cv_master.yaml` (**gitignored**) traz todos os fatos verdadeiros, um bullet por realização, com tags:

```yaml
experiences:
  - company: IORQ
    role: Engenheiro de Software
    period: 2024-02/2026-08
    bullets:
      - id: iorq-credit-llm
        text: Automação de análise de crédito com LLMs extraindo dados de Balanço Patrimonial e DRE...
        tags: [llm, fintech, python, document-extraction]
```

O LLM **só pode devolver IDs de bullets e a ordem deles**, mais um resumo de 2–3 linhas. Um validador rejeita qualquer saída com ID inexistente. O texto dos bullets é sempre o original.

Implementado na Fase 3 (`domain/cv.py`). O validador também rejeita: empresa ausente ou a
mais, bullet repetido, habilidade fora do mestre e resumo que cita tecnologia que o mestre
não cita. Rejeição → nova tentativa com o motivo → CV mestre sem ajuste. A carta (≤ 170
palavras, no idioma da vaga) é rejeitada se tiver campo para preencher, passar de 220
palavras, não tiver assinatura ou citar tecnologia que não está nem no CV nem na vaga. Só
vagas com nota ≥ `llm.documents_min_score` (70) recebem documentos, até
`llm.claude_daily_letters` (10) por execução.

---

## 7. Modelo de dados (SQLite)

| Tabela | Campos principais |
|---|---|
| `companies` | id, nome, setor, site, ats (greenhouse/lever/ashby/gupy/…), slug, contato_outreach, último_contato |
| `jobs` | id, fonte, id_externo, company_id, título, descrição, local, modelo, contrato, salário_min/max, url, coletada_em, hash |
| `scores` | job_id, embed_sim, llm_score, justificativa, red_flags, modelo_usado |
| `applications` | job_id, status (`queued` · `auto_applied` · `applied_manual` · `discarded` · `replied` · `interview` · `offer` · `rejected`), cv_variant_path, carta, respostas_json, timestamps |
| `outreach` | company_id, rascunho_id_gmail, assunto, corpo, status (`draft` · `sent` · `replied`), criado_em |
| `runs` | id, início, fim, etapa, contagens, erros |

---

## 8. Painel

FastAPI + Jinja2 + HTMX, em `localhost`. Sem projeto separado de frontend.

- **Hoje:** relatório da última noite (coletadas → filtradas → avaliadas → aplicadas/enfileiradas), erros.
- **Fila:** card por vaga com score, justificativa, red flags, CV ajustado, carta e respostas prontas para copiar; botões **Abrir vaga**, **Done**, **Descartar**.
- **Funil:** aplicadas → resposta → entrevista → proposta, por fonte e por nível.
- **Outreach:** rascunhos criados, marcar como enviado/respondido.
- **Mercado:** faixas salariais coletadas por nível e contrato.

Entregue na Fase 2: Hoje, Fila (Done/Descartar/Desfazer, filtro por nota, abas Aplicadas e
Descartadas) e Mercado. CV ajustado e carta entram no card na Fase 3; Funil na Fase 7; Outreach
na Fase 6. Nível, contrato e salário são extraídos do texto da vaga quando a fonte não informa.

---

## 9. Stack

Python 3.12 · FastAPI · SQLAlchemy 2 · Pydantic 2 · Alembic · SQLite · Playwright · httpx · Ollama (LLM + embeddings) · Jinja2 + HTMX · pytest · ruff · uv (gerenciador) · Docker opcional (o painel roda direto; Ollama nativo no Windows aproveita melhor a GPU).

### Estrutura proposta

```
night-shift/
├── config/                # *.yaml pessoais (gitignored) + *.example.yaml versionados
├── docs/
├── src/night_shift/
│   ├── domain/            # entidades, regras de score, políticas de risco
│   ├── application/       # casos de uso do pipeline
│   ├── ports/
│   ├── adapters/
│   │   ├── sources/       # greenhouse, lever, ashby, gupy, programathor, linkedin_alerts
│   │   ├── appliers/
│   │   ├── llm/           # ollama, claude_cli
│   │   ├── storage/       # sqlite
│   │   └── mail/          # gmail drafts
│   ├── web/               # painel
│   └── cli.py             # `night-shift run`, `night-shift serve`
├── .claude/skills/        # skills que limitam o Claude às tarefas de carta/outreach
└── tests/
```

---

## 10. Fases

| Fase | Entrega | Pronto quando |
|---|---|---|
| **0 — Fundação** | Repo, uv, estrutura, config, SQLite + Alembic, CI de lint/teste | `night-shift --help` roda e os testes passam |
| **1 — Coleta + ranking** | Fontes Greenhouse/Lever/Ashby + Gupy, filtros, embeddings, score local | Uma execução gera vagas ranqueadas no banco |
| **2 — Painel** | Telas Hoje, Fila (Done/Descartar) e Mercado | Consigo triar a noite anterior pelo navegador |
| **3 — CV e carta** | CV mestre, CV ajustado em PDF, carta via Claude | Cada vaga da fila tem CV e carta prontos |
| **4 — Agendamento + turn-off** | Task Scheduler, logs, `runs`, retomada após falha, `night-shift on/off` (seção 11.1) | Roda sozinho 7 noites seguidas e o `off` limpa tudo |
| **5 — Auto-apply baixo risco** | Applier Playwright para Greenhouse/Lever/Ashby, dry-run primeiro | Candidaturas automáticas registradas com print de confirmação |
| **6 — Outreach** | companies.yaml, rascunhos no Gmail, controle de recontato | N rascunhos/dia prontos para eu enviar |
| **7 — Extras** | Alertas do LinkedIn via Gmail, Programathor, funil | — |

O valor chega já na fase 2. Auto-apply fica para depois de eu confiar no score.

---

## 11. Guardrails

- **Privacidade:** CV, profile, companies com contatos, tokens e o `.db` ficam fora do git. Só os `*.example.yaml` são versionados.
- **Rate limit** educado por fonte, com `User-Agent` genérico e respeito a `robots.txt`.
- **Auto-apply com limite diário** e modo `--dry-run`. Toda candidatura automática salva print e payload.
- **Nunca enviar e-mail:** o token do Gmail tem só o escopo de rascunho (`gmail.compose`).
- **Recontato:** a mesma empresa não recebe outreach de novo antes de 60 dias.
- **Kill switch:** `config/profile.yaml → automation.enabled: false` para tudo que submete algo.
- **Turn-off total:** ver seção 11.1.

### 11.1 Turn-off (desligar tudo)

No Windows, um processo filho órfão (Chromium do Playwright, Ollama segurando VRAM, uvicorn) continua rodando depois que você fecha o terminal. Para isso existe um comando único que deixa o PC como se o projeto não existisse.

**Como acionar:**
- `night-shift off`, ou
- atalho na área de trabalho (`NightShift-OFF.lnk` → script `.ps1`), ou
- botão **Desligar tudo** no painel (ele se desliga por último).

**O que ele faz, em ordem:**

1. Sinaliza parada via arquivo `run/STOP`. O pipeline confere esse arquivo entre etapas e termina limpo, sem deixar uma candidatura pela metade.
2. Espera até 30 s pelo encerramento limpo.
3. Mata a árvore de processos registrada. Todo processo do projeto nasce dentro de um **Job Object** do Windows (via `pywin32`), com `KILL_ON_JOB_CLOSE`, então fechar o job mata Python, Chromium e workers de uma vez. Por garantia, os PIDs também ficam em `run/pids.json` e são mortos com `taskkill /T /F`.
4. Descarrega o modelo da GPU (`ollama stop <modelo>`) e, se `turn_off.stop_ollama: true`, encerra o serviço do Ollama.
5. Desativa as tarefas agendadas `NightShift\*` no Agendador de Tarefas. O `night-shift on` reativa.
6. Imprime um relatório: o que foi encerrado, a VRAM liberada e as tarefas desativadas. Se sobrar algum processo, ele é listado com o PID.

**Pronto quando:** depois do `off`, o Gerenciador de Tarefas não mostra nada do projeto, a VRAM volta ao nível de repouso e nada roda na noite seguinte até um `night-shift on`.

---

## 12. Decisões em aberto

- [ ] Qual modelo local exatamente (benchmark com 20 vagas rotuladas).
- [ ] Limiar de score para auto-apply (começar alto, ~85).
- [x] Endpoint da Gupy: API antiga morreu; lemos a página de busca (`robots.txt` libera). Sem paginação.
- [x] Lista inicial de empresas com ATS público: 16 em `config/companies.example.yaml`.
- [ ] Idioma da carta e do CV para vagas em inglês (ter CV mestre bilíngue?).
