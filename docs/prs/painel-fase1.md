## O que muda

Fase 1 da melhoria do painel: deixar claro **o que fazer agora** (referências: Huntr e Teal, rastreadores de candidatura).

**Hoje: "o que te espera"**
- Quatro blocos clicáveis no topo: e-mails de outreach prontos para enviar, vagas novas na fila (nota nos últimos 7 dias), candidaturas sem resposta há 7+ dias (hora de cobrar, como o Teal sugere) e a última busca.
- "Melhores vagas novas" em lista compacta (nota, cargo, empresa, stack); sem nota nova na semana, mostra as melhores da fila.
- Seção "Esperando resposta" quando há candidatura para cobrar.
- Os detalhes da última execução e o histórico foram para um bloco recolhível. Antes, uma busca só de outreach abria a página com cinco zeros.

**Outreach**
- Abas novas: **Com e-mail** (abre aqui quando há e-mail pronto) e **Sem e-mail**, além de Enviadas e Descartadas. O link antigo `?view=pendentes` continua funcionando.
- O texto de ajuda estava desatualizado (nota do LinkedIn e `output/cv/curriculo.pdf`). Agora diz qual CV anexar (o arquivo `cv_*_11xxx.pdf`, Python em português) e, na aba sem e-mail, como usar o link de recrutadores.
- O número no menu Outreach passa a ser o de e-mails prontos para enviar, não o total de rascunhos.

**Fila**
- Busca por cargo ou empresa (sem acento, sem caixa, vários termos), que filtra enquanto você digita (htmx troca só a lista e atualiza a URL).
- Ordenação: maior nota, mais recentes ou empresa A a Z. Os filtros mudam na hora, sem recarregar a página.
- Contagem de resultados e mensagem própria quando a busca não acha nada.

**Outros**
- O CSS leva a data do arquivo na URL (`style.css?v=...`), então o navegador não fica preso no estilo antigo depois de uma atualização.
- O texto de confirmação do "Buscar vagas" não fala mais em "gera CV".

## Como foi testado

- [x] `uv run ruff check .` e `uv run ruff format --check .`
- [x] `uv run pytest`: 293 passaram (novos: blocos do Hoje, "esperando resposta" só depois de 7 dias, vagas novas só com nota recente, busca e ordenação da Fila, abas com e sem e-mail do Outreach)
- [x] Rodado de verdade no navegador com o banco real: o Hoje mostra 11 e-mails prontos, 5 vagas novas, 0 para cobrar e a busca #20; digitar "getnet" na Fila deixa só as 2 vagas da Getnet e atualiza a URL; o Outreach abre em "Com e-mail (11)" com o nome do CV certo. No celular (375 px), os blocos ficam em 2 colunas. Sem erros no console.

## O que não foi coberto / riscos

- Fases 2 e 3 (avisos com desfazer, cartões compactos na Fila, atalhos de teclado, funil com arrastar e soltar) ficam para depois.

## Migrations

Nenhuma.

🤖 Generated with [Claude Code](https://claude.com/claude-code)
