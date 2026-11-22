## O que muda

Primeira parte da Fase 7: **aba Funil** no painel, para acompanhar cada candidatura da
aplicação até a proposta, com **anotações** por vaga.

> Base `main`, mas os commits ficam em cima da branch do outreach. Mergeie o **#10** primeiro; depois disso este PR mostra só o funil.

### Histórico de etapas

- Tabela `application_events`: toda troca de status de uma candidatura vira um evento, **automaticamente** (listener do SQLAlchemy no `Application.status`). Vale para qualquer caminho: Done no painel, `night-shift apply`, botões do funil.
- A migration preenche um evento inicial para as candidaturas que já existiam (data da aplicação).

### Aba Funil (`/funil`)

- **Topo**: quantas chegaram a cada etapa (aplicadas → resposta → entrevista → proposta) e a % de passagem entre elas, mais outreach enviados × responderam. A conversão usa o histórico: recusada depois da entrevista conta como tendo chegado à entrevista.
- **Conversão por fonte** (Greenhouse, Gupy…), recolhível.
- **Colunas**: Aplicadas, Resposta, Entrevista, Proposta e Recusadas. Cada card mostra empresa, fonte, linha do tempo das etapas e os botões da etapa seguinte ("Teve resposta", "Entrevista marcada", "Recebi proposta", "Recusada", "Voltar para aplicada").
- **Anotações** por vaga (tabela `job_notes`), com data, direto no card.
- Mover ou anotar atualiza o quadro inteiro na hora (HTMX), sem recarregar a página.

## Como foi testado

- [x] `uv run ruff check .` e `uv run ruff format --check .`
- [x] `uv run pytest`: 239 testes (5 novos). Cada troca de status vira evento e status repetido não duplica; conversões pelo histórico e por fonte (incluindo recusada depois de entrevista); mover e anotar; **migration a partir da revisão anterior** com uma candidatura existente, que ganha o evento com a data certa; página, mover, anotar, anotação vazia (422), etapa ou vaga inexistente (404), POST sem HTMX (403).
- [x] Navegador, numa **cópia** do banco com 7 candidaturas espalhadas pelas etapas: números e % no topo, colunas, linha do tempo; clique em "Teve resposta" moveu o card (Resposta 1 → 2) e recalculou a conversão; anotação salva; desktop e 375 px sem rolagem lateral.

## O que não foi coberto / riscos

- O funil só sabe o que você marcar: resposta, entrevista e proposta são cliques seus. (Ler respostas do Gmail para marcar sozinho fica para quando o conector estiver ligado.)

## Migrations

`4f2677f643f1`: tabelas `application_events` e `job_notes`, com preenchimento inicial dos eventos.

🤖 Generated with [Claude Code](https://claude.com/claude-code)
