## O que muda

Fase 6 do escopo: **outreach para empresas sem vaga aberta**. Para cada empresa da lista
(agora 88), o sistema acha o que ela publica no próprio site e escreve uma **nota de
conexão do LinkedIn** e um **e-mail**. Nada é enviado sozinho: você envia e marca no painel.

> PR empilhado sobre o #8 (`fase-5b/ao-vivo-cv-ingles`). Mergeie o #8 primeiro.

### Por que LinkedIn e não e-mail

Varri o site das 88 empresas (só leitura, robots.txt respeitado):

| | empresas |
|---|---|
| e-mail público de recrutamento | **1** (NeuralMind, `talentos@`) |
| só caixas gerais (contato, imprensa, suporte, vendas) | 32 |
| página de carreiras / banco de talentos | 64 |
| descrição no site | 85 |

E-mail de pessoa (nome.sobrenome@) nunca é usado nem adivinhado (LGPD), e caixa geral também não (é atendimento: baixa resposta e risco de spam). Decisão combinada: LinkedIn como canal principal, e-mail quando existir caixa de RH ou um contato seu no `companies.yaml`.

### Partes

- **Lista de empresas** (`config/companies.example.yaml`): 88, entre bancos digitais, gestoras e fundos, fintechs de pagamento e crédito, dados/identidade e IA, com site.
- **Descoberta** (`adapters/contacts.py`, `domain/contacts.py`): home + páginas de carreiras/contato linkadas + caminhos comuns (até 8 páginas por site), e-mails de `mailto:`, texto e HTML; só caixas de recrutamento do próprio domínio (`talentos@`, `recrutamento@`, `vagas@`, `rh@`…). Guarda também a página de carreiras e a descrição (meta description). Revarre a cada 30 dias. Contato manual do YAML nunca é trocado.
- **Mensagem** (`application/outreach.py`): nota do LinkedIn ≤ 300 caracteres (limite do LinkedIn) e e-mail ≤ 130 palavras, ligando 1–2 experiências reais ao que a empresa faz. Rejeita: nota longa, campo para preencher, falta de assinatura, tecnologia que não está no CV nem na descrição da empresa. Uma nova tentativa com o motivo.
- **Fila** (`adapters/storage/outreach.py`): até `llm.claude_daily_outreach` (agora **10**) por dia; empresas com e-mail primeiro, depois fintech → banco digital → IA → fundo → tech; sem recontato por 60 dias.
- **Pipeline/CLI**: etapas `contatos` e `outreach` (também no `run` e na página Ao vivo); `night-shift outreach [-n N]`.
- **Painel**: aba **Outreach** (Para enviar / Enviadas / Descartadas, contador no menu). Por empresa: setor, descrição, links para o site, a página de carreiras e a **busca de recrutadores no LinkedIn**; nota com contador de caracteres e **Copiar**; e-mail com **Copiar** e **Abrir no Gmail** (destinatário, assunto e texto preenchidos, você anexa `output/cv/curriculo.pdf`); **Marcar enviada**, **Descartar**, **Responderam**, **Desfazer**.

### Mudanças fora do outreach

- `sync_companies` não apaga mais o contato descoberto a cada execução.
- `PoliteClient` trata URL malformada como falha da fonte (o site da Caju tem `href="quero@caju.com.br"` e derrubava a varredura).
- Migration `cb66e58d4351`: `companies.contact_source_url`, `careers_url`, `contact_checked_at`, `about`; `outreach.to_address`, `linkedin_note`; status `discarded`.

## Como foi testado

- [x] `uv run ruff check .` e `uv run ruff format --check .`
- [x] `uv run pytest`: 234 testes (27 novos). Ranking de caixas de recrutamento, domínio próprio x de terceiros, descarte de e-mail de pessoa e caixas gerais, descoberta com sites falsos (link de carreiras, descrição, href com e-mail, robots.txt bloqueando, site fora do ar), todas as validações da mensagem, prioridade e janela de 60 dias, limite diário, nova tentativa, contato manual preservado, painel e ações.
- [x] Os testes pegaram um bug real: a janela de recontato comparava data sem fuso (SQLite) com data com fuso e quebraria assim que algo fosse marcado como enviado. Corrigido fazendo a comparação no SQL.
- [x] **Real**: `night-shift outreach -n 3` varreu os 88 sites em ~9 min (1 e-mail de RH, 64 páginas de carreiras, 85 descrições) e o Haiku escreveu 3 mensagens (NeuralMind por e-mail; Asaas e BizCapital por LinkedIn), notas com 216–261 caracteres, sem invenção. Aba Outreach conferida no navegador.

## O que não foi coberto / riscos

- A varredura não executa JavaScript: site 100% client-side pode esconder e-mail ou carreiras.
- Os sites da lista vieram do meu conhecimento do mercado; 3 bloquearam por robots.txt e alguns podem ter mudado de domínio.
- Envio por e-mail é pelo "Abrir no Gmail" (anexo manual); a API do Gmail ficou para depois.
- O link do LinkedIn é uma busca para você abrir; o sistema não acessa nem raspa o LinkedIn.

## Migrations

`cb66e58d4351` (colunas nullable, sem perda de dados).

🤖 Generated with [Claude Code](https://claude.com/claude-code)
