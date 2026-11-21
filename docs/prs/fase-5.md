## O que muda

Fase 5 do escopo, **redesenhada**: em vez de envio automático, **aplicação assistida**. O
sistema abre o formulário da vaga já preenchido, com CV ajustado e carta; você confere,
completa o que só você pode responder e clica em enviar.

### Por que não automático

Antes de escrever código, li a estrutura (sem preencher nada) de um formulário real de cada plataforma:

| | Greenhouse (QuintoAndar) | Lever (Stark Bank) | Ashby (Nubank) |
|---|---|---|---|
| Anti-robô | reCAPTCHA Enterprise | hCaptcha | reCAPTCHA Enterprise |
| Obrigatórias que travam | CPF, raça, gênero, orientação, deficiência | empresa atual, Sim/Não da vaga | pretensão salarial, níveis de experiência |

O sistema não contorna captcha, e envio marcado como robô costuma ser descartado sem aviso. Perguntas sensíveis e de autoavaliação não devem ser respondidas por um robô. Decisão registrada em docs/ESCOPO.md §13.

### Como funciona

- `domain/form_fields.py`: identifica o campo pelo **rótulo** (não por seletor de cada ATS): nome/sobrenome/nome completo, e-mail, telefone, cidade, LinkedIn, GitHub, empresa atual, carta, currículo. **Campos sensíveis** (CPF e outros documentos, raça, cor, gênero, orientação, deficiência, pronomes, idade/nascimento, religião, antecedentes) nunca são preenchidos, mesmo que uma resposta configurada case com eles. Respostas fixas por regex em `application.answers`.
- `adapters/applier/form_filler.py`: preenche só campos vazios, anexa o CV ajustado (no upload de currículo ou, sem rótulo claro, no primeiro upload), detecta captcha e lista os obrigatórios que sobraram, incluindo os marcados só com `*` no rótulo. **Nunca clica em enviar.**
- `adapters/applier/assisted.py`: navegador visível com perfil próprio (`data/browser-profile`), abre a URL do formulário no próprio ATS, preenche, tira print e mostra um aviso na página. Espera você enviar e reconhece a confirmação (texto ou URL nova); fechar a aba pula a vaga.
- `night-shift apply [-n N] [--job ID] [--preview]`: fila automática com CV ajustado pronto, respeitando `automation.daily_auto_apply_limit`. `--job` aceita vaga de qualquer fila (só Greenhouse/Lever/Ashby). `--preview` preenche num navegador invisível, tira print e fecha.
- Resultado gravado em `applications.answers.apply` (+ histórico); confirmação vira status `auto_applied`.
- Painel: aplicadas pelo night-shift contam na aba Aplicadas; o card mostra campos preenchidos, obrigatórios pendentes, captcha e links para os prints (servidos só de `output/applications`).
- CI instala o Chromium do Playwright.

## Como foi testado

- [x] `uv run ruff check .` e `uv run ruff format --check .`
- [x] `uv run pytest`: 193 testes (34 novos). Classificação de rótulos, todos os sensíveis bloqueados mesmo com resposta "pega-tudo", "Cidade" não confunde com "idade", "Nome da empresa" não vira nome da pessoa, reconhecimento de confirmação, URLs por ATS; com Chromium de verdade: formulário tipo Greenhouse e tipo Lever, valor existente não sobrescrito, obrigatório só por asterisco, espera da confirmação (aplicada, timeout, aba fechada) e sessão completa (prévia e envio simulado).
- [x] **Prévia no formulário real** do BTG (vaga 589, com autorização): 4 campos preenchidos (nome, sobrenome, e-mail, telefone), CV ajustado anexado, 7 campos sensíveis deixados em branco, reCAPTCHA detectado, nada enviado. A 1ª prévia mostrou "0 obrigatórios" com vários vazios no print: o BTG marca obrigatório só com `*` no rótulo. Corrigido e repetido: 11 obrigatórios listados.

## O que não foi coberto / riscos

- **Envio real não foi testado**: só quem envia é você. O reconhecimento da confirmação foi testado com página local; os textos reais de confirmação de cada ATS podem variar (a lista de padrões está em `CONFIRMATION`).
- A contagem de obrigatórios é aproximada: listas de seleção customizadas (ex.: universidade, ano de conclusão no BTG) às vezes não entram.
- No Windows, se `playwright install chromium` rodar num ambiente isolado, o navegador pode não aparecer para o seu usuário; rodar `uv run playwright install chromium` no seu terminal resolve (aconteceu aqui).
- Fila automática continua vazia com limiar 85 (maior nota até agora: 78); `--job` cobre o uso até lá.

## Migrations

Nenhuma.

🤖 Generated with [Claude Code](https://claude.com/claude-code)
