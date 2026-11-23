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
| Greenhouse / Lever / Ashby | API pública do job board da empresa | Formulário padrão, **mas com captcha** | **Baixo** | Aplicação assistida se score ≥ limiar |
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
| **5 — Aplicação assistida** | Playwright abre e preenche Greenhouse/Lever/Ashby; você confere e envia; prévia sem enviar | Candidaturas registradas com print do preenchimento e da confirmação |
| **6 — Outreach** | companies.yaml, rascunhos no Gmail, controle de recontato | N rascunhos/dia prontos para eu enviar |
| **7 — Extras** | Alertas do LinkedIn via Gmail, Programathor, funil | — |

O valor chega já na fase 2. Auto-apply fica para depois de eu confiar no score.

---

## 11. Guardrails

- **Privacidade:** CV, profile, companies com contatos, tokens e o `.db` ficam fora do git. Só os `*.example.yaml` são versionados.
- **Rate limit** educado por fonte, com `User-Agent` genérico e respeito a `robots.txt`.
- **Nada é enviado sozinho.** A aplicação é assistida (§13), com limite diário e modo `--preview`. Toda candidatura salva print do preenchimento e da confirmação.
- **Nunca enviar e-mail:** o token do Gmail tem só o escopo de rascunho (`gmail.compose`).
- **Recontato:** a mesma empresa não recebe outreach de novo antes de 60 dias.
- **Kill switch:** `config/profile.yaml → automation.enabled: false` para tudo que submete algo.
- **Turn-off total:** ver seção 11.1.

### 11.1 Turn-off (desligar tudo)

No Windows, um processo filho órfão (Chromium do Playwright, Ollama segurando VRAM, uvicorn) continua rodando depois que você fecha o terminal. Para isso existe um comando único que deixa o PC como se o projeto não existisse.

**Como acionar:**
- `night-shift off`, ou
- atalho "night-shift OFF" na área de trabalho (criado por `night-shift shortcuts`), ou
- botão **Desligar tudo** no painel (ele se desliga por último).

**O que ele faz, em ordem:**

1. Sinaliza parada via arquivo `run/STOP`. O pipeline confere esse arquivo entre etapas e termina limpo, sem deixar uma candidatura pela metade.
2. Espera até 30 s pelo encerramento limpo.
3. Mata a árvore de processos registrada. Todo processo do projeto nasce dentro de um **Job Object** do Windows (via `pywin32`), com `KILL_ON_JOB_CLOSE`, então fechar o job mata Python, Chromium e workers de uma vez. Por garantia, os PIDs também ficam em `run/pids.json` e são mortos com `taskkill /T /F`.
4. Descarrega o modelo da GPU (`ollama stop <modelo>`) e, se `turn_off.stop_ollama: true`, encerra o serviço do Ollama.
5. Desativa as tarefas agendadas `NightShift\*` no Agendador de Tarefas. O `night-shift on` reativa.
6. Imprime um relatório: o que foi encerrado, a VRAM liberada e as tarefas desativadas. Se sobrar algum processo, ele é listado com o PID.

**Pronto quando:** depois do `off`, o Gerenciador de Tarefas não mostra nada do projeto, a VRAM volta ao nível de repouso e nada roda na noite seguinte até um `night-shift on`.

**Implementado na Fase 4** (`runtime/turn_off.py`). Diferenças do plano: o kill usa
`psutil` na árvore de cada PID registrado (em vez de `taskkill`), e o Ollama só é tocado
quando `llm.provider: ollama` ou `turn_off.stop_ollama: true`. Verificado de verdade com a
tarefa agendada no meio da etapa de nota: o pipeline parou sozinho em 7 s, entre duas vagas,
e a execução ficou registrada como `stopped`.

### 11.2 Execução noturna

- `night-shift schedule install --at 02:00` cria a tarefa `\NightShift\Nightly` a partir de
  um XML: pasta de trabalho do projeto, acorda o PC da suspensão, roda na bateria, recupera
  execução perdida (`StartWhenAvailable`), no máximo 3 h, uma instância por vez, só com o
  usuário logado (sem senha, sem admin).
- Cada comando do pipeline grava `logs/<data>-<comando>.log` (os 60 mais recentes ficam).
- Só um comando do pipeline roda por vez; o segundo é recusado e a recusa vai para o log.
- Execução que ficou `running` (PC desligado no meio) vira `failed` na próxima, que continua
  de onde parou porque todas as etapas são idempotentes.

---

## 12. Decisões em aberto

- [ ] Qual modelo local exatamente (benchmark com 20 vagas rotuladas).
- [ ] Limiar de score para auto-apply (começar alto, ~85).
- [x] Endpoint da Gupy: API antiga morreu; lemos a página de busca (`robots.txt` libera). Sem paginação.
- [x] Lista inicial de empresas com ATS público: 16 em `config/companies.example.yaml`.
- [ ] Idioma da carta e do CV para vagas em inglês (ter CV mestre bilíngue?).

---

## 13. Aplicação assistida (Fase 5)

**Decisão de 21/11/2026:** envio 100% automático descartado. Os formulários reais das três
plataformas (Greenhouse/QuintoAndar e BTG, Lever/Stark Bank, Ashby/Nubank) têm:

- **proteção anti-robô**: reCAPTCHA Enterprise (Greenhouse, Ashby) e hCaptcha (Lever). O
  sistema não contorna captcha, e envio marcado como robô costuma ser descartado em silêncio;
- **perguntas obrigatórias que só o candidato responde**: CPF, raça, gênero, orientação,
  deficiência, pretensão e remuneração anterior, autoavaliação técnica, parentesco.

`night-shift apply` abre cada vaga da fila automática num navegador visível, preenche o que é
seguro (nome, e-mail, telefone, cidade, LinkedIn, GitHub, empresa atual, respostas fixas de
`application.answers`), anexa o CV ajustado e cola a carta. Campo sensível nunca é tocado,
mesmo com resposta configurada. Você completa, resolve o captcha e envia; o sistema reconhece
a confirmação, tira print e marca como aplicada (`auto_applied`). `--preview` preenche num
navegador invisível, tira print e fecha sem enviar. `--job ID` aplica uma vaga de qualquer fila.

Medido no formulário real do BTG (prévia): 4 campos preenchidos, CV anexado, 7 sensíveis
deixados em branco, 11 obrigatórios para o candidato, reCAPTCHA presente.

---

## 14. Acompanhamento ao vivo e CV em inglês (21/11/2026)

- **Primeira rodada acompanhada** em vez de "7 noites seguidas": o usuário escolhe a hora e
  assiste pela página **Ao vivo** (`/ao-vivo`, HTMX com atualização a cada 2 s, sem React).
  O pipeline grava etapa, item atual, contadores, fim do limite de LLM e caminho do log na
  linha do `Run` a cada unidade de trabalho. **Rodar agora** dispara a tarefa agendada (roda
  fora do processo do painel); **Parar** usa o mesmo `run/STOP` do `off`.
- **CV em inglês**: `config/cv_master.en.yaml` com os mesmos IDs do mestre (`night-shift cv
  check` confere). Vaga em inglês → seleção, PDF (títulos e datas em inglês, arquivo `-en.pdf`)
  e carta em inglês.
- **CV completo em PDF** para aplicações manuais: `night-shift cv pdf` gera
  `output/cv/cv_<nome>_<perfil><idioma><3 dígitos>.pdf` (perfil 1 python, 2 ia, 3 java;
  idioma 1 pt, 2 en; desde 23/11/2026), com todas as habilidades. Desde 23/11/2026 não há
  CV ajustado por vaga: cada vaga usa o CV fixo do seu tipo (no máximo 6 arquivos); o LLM só
  escreve a carta.

---

## 15. Outreach (Fase 6, 21/11/2026)

**Decisão:** LinkedIn é o canal principal; e-mail só quando a empresa publica uma caixa de
recrutamento ou quando o usuário adiciona um contato. Motivo, medido nos 88 sites da lista:
**1** publica e-mail de RH (NeuralMind, `talentos@`), 32 só têm caixas gerais (contato,
imprensa, suporte, vendas), 64 têm página de carreiras e 85 têm descrição. E-mail de pessoa
(nome.sobrenome@) nunca é usado nem adivinhado (LGPD); caixa geral também não.

**Atualização (23/11/2026):** o contato geral da empresa passou a valer quando não há caixa de
recrutamento: `contato@`, `faleconosco@`, `hello@`/`ola@`, `info@`, sempre do próprio domínio.
Recrutamento continua com prioridade (mesmo em outra página do site). Seguem fora: e-mail de
pessoa e caixas de outro assunto (imprensa, suporte, vendas, privacidade/DPO, ouvidoria).
`night-shift outreach --recheck -n 0` varre de novo todos os sites sem escrever e-mails; um
rascunho sem destinatário ganha o e-mail assim que ele é encontrado.

- `night-shift outreach` (e a etapa no `run`): varre o site de cada empresa (robots.txt
  respeitado, a cada 30 dias) atrás do e-mail público (recrutamento ou contato geral), da página de carreiras e da
  descrição; escreve até `llm.claude_daily_outreach` (10) **e-mails** por dia, validados (sem
  campo para preencher, com assinatura, sem tecnologia fora do CV e da descrição). A nota de
  conexão do LinkedIn foi removida em 23/11/2026: a abordagem a recrutadores no LinkedIn é
  feita à mão, com mensagem única; o e-mail segue as regras e o modelo de `outreach` no
  `profile.yaml` (abertura "Sou ...", sem cerimônia, sem citar ex-empregadores).
- Prioridade: empresas com e-mail, depois fintech → banco digital → IA → fundo → tech.
  Sem recontato por 60 dias depois de enviada.
- Aba **Outreach** do painel: e-mail pronto para copiar, link para buscar
  recrutadores da empresa no LinkedIn, página de carreiras, **Abrir no Gmail** com tudo
  preenchido (você anexa o CV e envia), **Marcar enviada**, **Descartar**, **Responderam**.
  Nada sai sozinho. A API do Gmail ficou para depois, se o volume de e-mail crescer.

---

## 16. Perfis de CV por stack (Fase 8, 22/11/2026)

- Três perfis, cada um com PT e EN: **Python backend** (`cv_master`), **IA/LLM** (`cv_ia`) e
  **Java** (`cv_java`, só júnior, com foco em Programação Orientada a Objetos e o projeto de
  conclusão da SPTech: monitoramento de hardware para totens, em Java com Spring Boot).
- Classificação da vaga (`domain/stacks.py`): o título manda; na descrição só contam sinais
  fortes de IA (LLM, IA generativa, machine learning, RAG, agentes), porque muita empresa cita
  "IA" de passagem. Sem pista, perfil Python.
- Filtro com níveis por stack (`preferences.stack_levels`); "java" saiu dos termos bloqueados
  e "c#" entrou. Similaridade (palavras-chave do próprio perfil), nota (prompt com os níveis
  da stack), CV ajustado e carta usam o perfil da vaga.
- PDF sempre em uma página (reduz fonte até 82%, depois tira cursos e bullets finais).
- `rank --rescreen` reclassifica e refaz o filtro das vagas cortadas.
- Medido: das 1.379 vagas, 131 IA, 78 Java e 1.170 Python; passaram no filtro 13 IA, 12 Java
  júnior e 36 Python. As primeiras Java júnior levaram 55–58: o Haiku pesa que o Java é
  acadêmico e a vaga pede Java profissional, avaliação honesta.
