## O que muda

Fase 2 da melhoria do painel: mais rápido de usar e com retorno a cada ação.

**Avisos com Desfazer**
- Done, Descartar e Voltar para fila (Fila), Marcar enviada, Descartar, Responderam e Voltar para enviar (Outreach) e mover no Funil mostram um aviso no canto da tela, por exemplo "Descartada: <cargo> · <empresa>".
- Done, Descartar, Marcar enviada e Descartar (Outreach) trazem botão **Desfazer** (6 segundos, ou a tecla `z`).
- O servidor manda o aviso no cabeçalho `HX-Trigger` (`toast(...)` em `web/app.py`); `static/app.js` mostra o aviso. O Desfazer aciona o botão de desfazer do próprio cartão, o mesmo caminho de um clique normal.
- Cuidado registrado no código: o campo do cartão no evento se chama `card`, não `target`. O htmx usa `target` do `HX-Trigger` para escolher onde disparar o evento, e `"target": null` quebrava a resposta (o cartão não era trocado).

**Cartões compactos na Fila**
- Cada vaga ocupa poucas linhas: nota, cargo, empresa, stack, nível, salário, quantidade de alertas e a justificativa do LLM numa linha só. O resto (fila, justificativa completa, alertas, formulário testado, carta, descrição) abre em **Detalhes**. Cabem cerca de 7 vagas na tela, contra 2 antes.
- O botão do CV mostra o código do arquivo (ex.: "CV 11894"); o nome completo fica no título do botão.

**Atalhos de teclado** (ajuda com `?` ou no link "atalhos" do rodapé)
- `j`/`k` navegam entre os cartões (Fila e Outreach), `o` ou `Enter` abre os detalhes, `a` abre a vaga (ou o Gmail no Outreach), `c` abre o CV, `d` Done ou Marcar enviada, `x` descarta, `z` desfaz, `/` vai para a busca, `b` Buscar vagas (com confirmação), `g` + `h`/`v`/`f`/`u`/`o`/`m` muda de página, `Esc` fecha a ajuda ou sai de um campo.
- Atalhos não disparam enquanto você digita num campo; `Enter` num link ou botão focado continua sendo o clique normal; `?` funciona também quando o teclado manda `/` com Shift (ABNT2).
- Depois de Done/Descartar, a seleção passa para a próxima vaga.

**Outros**
- A versão na URL dos arquivos estáticos (`?v=`) agora considera todos os arquivos de `static/`, incluindo o `app.js`.

## Como foi testado

- [x] `uv run ruff check .` e `uv run ruff format --check .`
- [x] `uv run pytest`: 295 passaram (novos: aviso com Desfazer em Done/Descartar, sem Desfazer no Voltar para fila, campo `card` e nunca `target`, aviso no Outreach e no Funil, cartão compacto com `data-key` e página com ajuda, avisos e `app.js`)
- [x] Rodado de verdade no navegador com o banco real: `j` `j` seleciona a segunda vaga, `o` abre os detalhes, `x` descarta (fila 64 → 63, aviso aparece), `z` desfaz (cartão volta, fila 64, aviso "De volta na fila"), sem erros no console; `g` `h` vai para o Hoje; a ajuda abre com `?` e com `/`+Shift e fecha com `Esc`. A vaga usada no teste ficou como estava (na fila).

## O que não foi coberto / riscos

- Na automação de teste, `Shift+/` chega como tecla vazia; o `?` foi conferido disparando o evento como o navegador faz.
- Fase 3 (lembrete de follow-up, funil com arrastar e soltar, Mercado dentro do Hoje) fica para depois.

## Migrations

Nenhuma.

🤖 Generated with [Claude Code](https://claude.com/claude-code)
