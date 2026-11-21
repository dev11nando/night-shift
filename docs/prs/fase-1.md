## O que muda

Fase 1 do escopo (docs/ESCOPO.md §10): **coleta + ranking**. O sistema busca vagas em
Greenhouse, Lever, Ashby (16 empresas) e Gupy, corta o que não é do perfil por regra, calcula a
similaridade vaga × CV com embeddings e dá nota de 0 a 100 às melhores com um LLM local.

### Fluxo (`night-shift run`)

1. **collect**: busca vagas em todas as fontes e deduplica por fonte+id e por hash do conteúdo (a mesma vaga em duas fontes entra uma vez).
2. **screen**: filtro por regra, sem custo. Corta por título fora do perfil, termos bloqueados (estágio, sales, mobile...), nível fora das preferências, falta de keyword da stack e local incompatível para presencial/híbrido. O motivo do corte fica gravado.
3. **embed_rank**: similaridade de cosseno entre CV e vaga via Ollama (`bge-m3`).
4. **llm_score**: as top N por similaridade (padrão 30) recebem nota, justificativa e red flags do `qwen3:8b`, com saída JSON forçada por schema. As que sobrarem ficam para a noite seguinte.

### Principais arquivos

| Camada | Arquivos |
|---|---|
| Domínio | `domain/job.py` (JobPosting + hash), `domain/text.py` (nível e modelo de trabalho), `domain/filters.py` |
| Portas | `ports/__init__.py`: JobSource, Embedder, LLMProvider |
| Fontes | `adapters/sources/ats.py` (Greenhouse/Lever/Ashby), `adapters/sources/gupy.py` |
| LLM | `adapters/llm/ollama.py` |
| Aplicação | `application/pipeline.py`, `application/scoring.py` (prompt e rubrica) |
| Persistência | `adapters/storage/repository.py` + migration nova |
| CLI | `run`, `collect`, `rank`, `jobs`, `companies probe` |

### Decisões que mudaram o escopo

- **Gupy:** a API pública de busca responde 404. Lemos o `__NEXT_DATA__` da página de busca do portal (o `robots.txt` libera). Só a 1ª página (~12 vagas) por termo, então é a fonte mais frágil; se o layout mudar, ela vira `SourceError` e o resto segue.
- **Embeddings via Ollama**, em vez de sentence-transformers: evita ~3 GB de torch e usa a mesma GPU.
- **Faixa de nível** ("Pleno/Sênior") conta como o menor nível, para não perder vaga que aceita pleno.
- **Lista inicial de 16 empresas** com job board público validado em 21/11/2026, em `config/companies.example.yaml`.

## Como foi testado

- [x] `uv run ruff check .` e `uv run ruff format --check .`
- [x] `uv run pytest`: 75 testes. Fontes contra respostas no formato real das APIs, filtro, adapter Ollama com transporte falso, e pipeline ponta a ponta no SQLite com fontes/embedder/LLM falsos (idempotência, top N, sobras, fonte quebrada, LLM fora do ar, STOP).
- [x] Rodado de verdade: `night-shift collect` trouxe **1.413 vagas**, **57 passaram** no filtro (1.135 título fora do perfil, 121 sênior/staff, 61 termo bloqueado, 9 local, 9 sem stack).

## O que não foi coberto / riscos

- **A nota do LLM não rodou com o modelo real**: o Ollama ainda não está instalado na máquina. Sem ele, o `rank` falha com mensagem clara (`Ollama inacessível` / `ollama pull <modelo>`) e o que foi coletado continua no banco.
- A qualidade do prompt e da rubrica só vai ser medida no benchmark com ~20 vagas rotuladas (decisão em aberto no escopo).
- Gupy sem paginação: "python" tem 15 vagas, vêm 12.
- Se o CV mudar, a similaridade das vagas já avaliadas não é recalculada.

## Migrations

`f701b1b3c69f`: `jobs.published_at`, `scores.filter_reason`, `scores.scored_at` (todas nullable, sem perda de dados).

🤖 Generated with [Claude Code](https://claude.com/claude-code)
