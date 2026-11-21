## O que muda

Fase 3 do escopo (docs/ESCOPO.md §10): **CV ajustado e carta de apresentação por vaga**. Para
as melhores vagas da fila (nota ≥ 70, até 10 por execução), o sistema gera um PDF do CV
reorganizado para a vaga e uma carta curta, os dois sem inventar nada.

### CV ajustado sem invenção (`domain/cv.py`)

O LLM não escreve o CV. Ele devolve só uma **seleção** (`CVSelection`):
- quais bullets de cada experiência, por ID, em ordem de relevância;
- quais habilidades, até 14, mais relevantes primeiro;
- um resumo de 2–3 frases.

`apply_selection` valida contra o CV mestre e **rejeita**: empresa ausente (sumir com emprego cria buraco no CV) ou empresa que não existe, ID de bullet inexistente ou repetido, experiência sem bullet, habilidade fora do mestre, e resumo que cita tecnologia que o mestre não cita (léxico de ~45 tecnologias). O texto de cada bullet sempre vem do mestre.

Rejeitou → **nova tentativa com o motivo no prompt** → se falhar de novo, usa o CV mestre sem ajuste e registra o erro.

### PDF (`adapters/render/cv_pdf.py`)

fpdf2 com a Arial do Windows (Unicode completo; sem ela, cai para Helvetica com troca de caracteres). Uma coluna, texto selecionável, sem tabela nem imagem, para os ATS lerem bem. Cabeçalho com nome, título e contato; Resumo, Experiência (com período "Fev/2024 – Ago/2026"), Habilidades, Formação, Cursos e Idiomas. Saída em `output/cv/<job_id>-<empresa>.pdf` (gitignored).

### Carta (`application/documents.py`)

No idioma da vaga (PT ou EN, detectado pelo texto), até 170 palavras, 3 parágrafos, citando algo específico da vaga e 1–2 realizações reais. Validação: rejeita campo para preencher (`[Nome]`), mais de 220 palavras, falta de assinatura e tecnologia que não está nem no CV nem na vaga (citar a stack da vaga é permitido). Também com uma nova tentativa.

### Pipeline, CLI e painel

- Etapa `documents` no pipeline. O limite de tempo agora é **compartilhado** entre as etapas de LLM da mesma execução (nota + documentos).
- `night-shift docs [-n N] [--regenerate]`; o `night-shift run` passa a incluir a etapa.
- Config: `llm.documents_min_score` (70), `llm.documents_model` (haiku), `llm.claude_daily_letters` (10 por execução). CV mestre ganha `headline` e `contact`.
- Painel: botão **CV ajustado** (abre o PDF) e bloco **Carta de apresentação** com assunto e botão **Copiar carta**. A rota do PDF só serve arquivo de dentro de `output/cv/`, mesmo que o banco aponte para outro caminho.

## Como foi testado

- [x] `uv run ruff check .` e `uv run ruff format --check .`
- [x] `uv run pytest`: 146 testes (28 novos). Todas as regras do validador do CV, termos inventados, CV mestre como fallback, formato de período, PDF gerado; idioma, prompts e todas as rejeições da carta; etapa no pipeline com LLM falso (gera e salva, retry com feedback, carta ruim duas vezes → CV sem carta, não regenera, nota mínima, LLM indisponível); painel mostra carta e link e recusa PDF fora da pasta.
- [x] **Rodado de verdade com o Haiku** em 2 vagas do BTG (notas 78 e 72): ~25 s por vaga para seleção + carta, nenhuma seleção rejeitada. O PDF tem 1 página e os bullets e habilidades foram reordenados para a vaga.
- [x] A 1ª versão das cartas tinha dois problemas: falava da IORQ no presente ("desenvolvo") e se desculpava por não saber .NET/Angular. O prompt agora exige passado para experiência encerrada e proíbe apontar lacuna. Regenerado com `docs --regenerate`: as duas cartas saíram corretas.
- [x] Painel real: as duas vagas mostram carta e link, e `/jobs/589/cv` devolve o PDF (200, application/pdf).

## O que não foi coberto / riscos

- **CV sempre em português**: para vaga em inglês a carta sai em inglês, mas o CV não (CV mestre bilíngue continua decisão em aberto).
- O léxico de "tecnologias inventadas" é uma lista fixa; algo fora dela que o LLM inventar no resumo passaria. O texto dos bullets nunca é do LLM, então o risco fica restrito ao resumo de 2–3 frases.
- Fonte Arial depende do Windows; em outro SO cai para Helvetica (sem bullet "•" e travessão).
- Amostra real pequena (2 vagas).

## Migrations

Nenhuma. CV e carta usam `applications.cv_variant_path` e `applications.cover_letter`, que já existiam; o assunto vai em `applications.answers.letter_subject`.

🤖 Generated with [Claude Code](https://claude.com/claude-code)
