## O que muda

Fase 8: **um perfil de CV por stack**. Cada vaga é classificada em Python, IA/LLM ou Java, e
o filtro, a nota, o CV ajustado e a carta usam o perfil daquela stack. Java só para júnior,
com o currículo focado em Programação Orientada a Objetos.

### Perfis (config local, fora do git)

| Perfil | Arquivo | Níveis | Ênfase |
|---|---|---|---|
| Python backend | `cv_master.yaml` (+ `.en`) | júnior, pleno | o CV de antes |
| IA / LLM | `cv_ia.yaml` (+ `.en`) | júnior, pleno | crédito com LLM e agentes antifraude primeiro |
| Java | `cv_java.yaml` (+ `.en`) | só júnior | POO, SOLID, DDD, arquitetura; seção **Projetos** com o TCC (monitoramento de hardware para totens, Java + Spring Boot) |

Todos só com fatos do CV original e do que o usuário contou do projeto.

### Código

- **CV**: seção `projects` no modelo, no texto e na checagem PT×EN; `cv check` e `cv pdf` cobrem todos os perfis (`curriculo-<perfil>.pdf`, `resume-<perfil>-en.pdf`).
- **PDF sempre em 1 página**: reduz fonte e espaçamento até 82%, depois tira a seção de cursos e, por último, os bullets finais da experiência mais longa (mínimo 2).
- **Classificação** (`domain/stacks.py`): título primeiro ("Java/Python" é Java); na descrição só sinais fortes de IA contam. Coluna `jobs.stack` (migration `e51c0ad3c6e7`), preenchida na coleta.
- **Filtro**: `preferences.stack_levels` (python/ia: júnior e pleno; java: júnior). "java" saiu dos termos bloqueados e "c#" entrou.
- **Pipeline**: similaridade com palavras-chave do perfil da vaga (um embedder por perfil), nota com o CV e os níveis da stack no prompt, CV ajustado e carta a partir do perfil. Quem passa um CV só continua funcionando (vira o perfil padrão).
- **CLI**: `rank --rescreen` reclassifica a stack de todas as vagas e refaz o filtro das cortadas.
- **Painel**: tag de stack no card e filtro por stack na Fila.

## Como foi testado

- [x] `uv run ruff check .` e `uv run ruff format --check .`
- [x] `uv run pytest`: 266 testes (24 novos). Classificação (inclui JavaScript ≠ Java, "IA" de passagem não vira IA, C#), níveis por stack no filtro e no prompt, pipeline usando o CV de cada perfil na similaridade, na nota e no PDF, `KeywordEmbedder` como fábrica, `--rescreen`, filtro por stack no painel, PDF que precisa encolher e cortar para caber em 1 página, projetos na tradução.
- [x] **PDFs reais**: os 6 (3 perfis × PT/EN) com 1 página cada, conferidos visualmente.
- [x] **Rodada real**: `rank --rescreen` reclassificou as 1.379 vagas (131 IA, 78 Java, 1.170 Python); passaram 13 IA, 12 Java júnior e 36 Python. As Java júnior avaliadas levaram 55–58, com justificativa coerente (Java só acadêmico).
- [x] A rodada real pegou 2 coisas que os testes não pegavam: a classe `KeywordEmbedder` era tratada como embedder pronto (corrigido + teste) e a descrição com "IA" de passagem classificava 473 vagas como IA (critério endurecido + testes).

## O que não foi coberto / riscos

- Java júnior tende a ficar abaixo de 70, então não recebe CV e carta automáticos (`llm.documents_min_score`). Dá para gerar à mão com `docs` depois de ajustar o limiar, se fizer sentido.
- O bullet "modelagem orientada a objetos do domínio" do projeto foi escrito a partir do relato do usuário; ele vai revisar.

## Migrations

`e51c0ad3c6e7`: `jobs.stack` (nullable, com índice).

🤖 Generated with [Claude Code](https://claude.com/claude-code)
