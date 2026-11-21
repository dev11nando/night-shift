## O que muda

Fase 2 do escopo (docs/ESCOPO.md §10): **painel local** para triar a noite anterior pelo
navegador. `night-shift serve --open` sobe FastAPI + Jinja2 + HTMX em `http://127.0.0.1:8765`,
acessível só desta máquina.

### Telas

| Tela | O que mostra |
|---|---|
| **Hoje** | Última execução: status, duração, funil (coletadas → novas → filtro → CV → LLM), erros, as 5 melhores notas da execução e o histórico das anteriores |
| **Fila** | Vagas com nota do LLM e sem decisão, da maior nota para a menor, com filtro de nota mínima. Card com nota, justificativa, red flags, tags (modelo, nível, contrato, salário) e descrição recolhível. Botões **Abrir vaga**, **Done** (já me candidatei) e **Descartar**; abas Aplicadas e Descartadas com **Desfazer** |
| **Mercado** | Mediana das faixas salariais publicadas por nível e contrato, mais a lista das vagas com salário |

Done/Descartar trocam só o card (HTMX) e atualizam o contador da fila no menu sem recarregar a página. A decisão vira uma linha em `applications` (`applied_manual` / `discarded`) com o risco da fonte.

### Enriquecimento das vagas

Quase nenhuma fonte informa nível, contrato ou salário em campos próprios. Por isso agora a coleta extrai do texto:
- **nível** pelo título (já existia, agora é gravado);
- **contrato** quando o texto cita só CLT ou só PJ;
- **salário** pela primeira faixa `R$ X (a R$ Y)` plausível como mensal (R$ 1.000 a R$ 60.000).

`night-shift db enrich` aplica isso às vagas já coletadas (663 atualizadas no banco local).

### Principais arquivos

- `web/app.py`: rotas, filtros de template e proteção CSRF (POST exige o header `HX-Request`)
- `web/templates/`: `hoje`, `fila`, `mercado`, `_card`, `_decided`
- `web/static/style.css`: tema claro/escuro pelo sistema, layout de celular
- `adapters/storage/review.py`: consultas da fila, decisões, execuções e medianas
- `domain/enrich.py` e `domain/text.py`: extração de contrato e salário
- `cli.py`: comandos `serve` e `db enrich`

## Como foi testado

- [x] `uv run ruff check .` e `uv run ruff format --check .`
- [x] `uv run pytest`: 97 testes (22 novos): páginas vazias, funil e erros, ordem e filtro da fila, Done/Descartar/Desfazer, idempotência, contador OOB, 403 sem header HTMX, 404, medianas do Mercado, extração de salário e contrato.
- [x] Rodado de verdade no navegador, contra uma **cópia** do banco local com 30 notas fictícias (o Ollama ainda não está instalado): Hoje, Fila, clique em Done (card vira "Aplicada · Desfazer" e o contador vai de 30 para 29), Mercado; em tema escuro e claro, e em 375px de largura sem rolagem lateral.

## O que não foi coberto / riscos

- **Sem dados reais de nota**: a fila do banco real fica vazia até o Ollama rodar o `rank`.
- **Mercado tem amostra mínima**: das 1.379 vagas, só 1 publica salário reconhecível. A tela é honesta sobre isso, mas vai precisar de mais fontes (Gupy/Programathor costumam publicar mais).
- Os contadores das abas da Fila só atualizam ao recarregar; o do menu atualiza na hora.
- HTMX vem da CDN (unpkg, versão fixa 2.0.4); sem internet os botões não funcionam.

## Migrations

Nenhuma.

🤖 Generated with [Claude Code](https://claude.com/claude-code)
