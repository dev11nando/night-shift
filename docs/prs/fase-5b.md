## O que muda

Preparação para a **primeira rodada acompanhada**: página **Ao vivo** no painel, **CV em
inglês** para vagas em inglês e **PDFs do CV completo** para as aplicações manuais.

### 1. Painel ao vivo (`/ao-vivo`)

- O pipeline grava o progresso na linha do `Run` a cada unidade de trabalho: etapa, item atual ("[3/30] Vaga — Empresa"), contadores, erros, quando acaba o limite de LLM e o caminho do log. Migration `47538c2426f4`: `runs.current_item`, `runs.budget_ends_at`, `runs.log_path`.
- A página mostra a trilha de etapas (Coleta → Filtro → Similaridade → Nota do LLM → CV e carta), tempo decorrido e restante, item atual, contadores, notas saindo na hora, o fim do log e os erros. Enquanto roda, atualiza a cada 2 s via HTMX (sem React nem build de frontend).
- **Parar** usa o mesmo `run/STOP` do `off`. **Rodar agora** dispara a própria tarefa agendada, então a execução roda fora do processo do painel; recusa se já houver execução ou se a tarefa estiver desligada.
- O log só é lido se estiver dentro de `logs/`.

### 2. CV em inglês

- `config/cv_master.en.yaml` (opcional, gitignored) com os **mesmos IDs** de bullet do mestre. `translation_problems` aponta experiência, bullet faltando ou sobrando, ordem, período e quantidade de habilidades diferentes.
- Vaga em inglês (detectada pelo texto) usa o CV em inglês na seleção, no resumo, no PDF (títulos "Summary/Experience…", datas "Feb 2024 – Aug 2026", arquivo `-en.pdf`) e na carta. Sem o arquivo, cai para o português como antes.

### 3. Comando `night-shift cv`

- `cv check`: valida o mestre e a tradução.
- `cv pdf`: gera o CV completo, sem ajuste por vaga, em `output/cv/curriculo.pdf` e `output/cv/resume-en.pdf`, para anexar nas aplicações manuais.

### Correções encontradas no caminho

- O CV completo cortava as habilidades em 14 (limite do CV ajustado); agora mostra todas.
- A etapa de nota e a de documentos não apareciam na página ao vivo quando não havia vaga para processar; agora marcam a etapa ao começar.

## Como foi testado

- [x] `uv run ruff check .` e `uv run ruff format --check .`
- [x] `uv run pytest`: 203 testes (10 novos). Tradução ok e cada tipo de divergência, datas e PDF em inglês, CV completo sem corte; vaga em inglês recebe CV `-en` e vaga em português o original; progresso gravado no meio da execução; página ao vivo sem execução, rodando (atualização, etapa ativa e concluída, item atual, contadores, tempo restante, log) e concluída (sem atualização, log fora de `logs/` não lido), Parar e Rodar agora com header HTMX obrigatório.
- [x] `night-shift cv check` no CV real: a tradução bate. `cv pdf` gerou os dois PDFs, conferidos página a página (17 habilidades em cada).
- [x] Navegador: `/ao-vivo` com o banco real (execução antiga) e com uma **cópia** do banco simulando uma execução em andamento: trilha, relógio avançando sozinho (4min 19s → 4min 23s), contadores, log, **Parar** criando o STOP só na pasta da cópia; sem rolagem lateral no desktop e em 375 px.
- [ ] **Rodar agora** de verdade não foi clicado: a primeira rodada real fica para a hora que você escolher.

## O que não foi coberto / riscos

- A tradução do CV foi feita por mim a partir do seu CV; **revise o texto** de `config/cv_master.en.yaml`.
- Execuções anteriores a esta versão aparecem sem etapa e sem log na página ao vivo.

## Migrations

`47538c2426f4`: `runs.current_item`, `runs.budget_ends_at`, `runs.log_path` (nullable).

🤖 Generated with [Claude Code](https://claude.com/claude-code)
