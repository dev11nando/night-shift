## O que muda

O outreach passa a aceitar o **e-mail geral de contato** da empresa quando ela não publica uma caixa de recrutamento (escopo §15).

- `domain/contacts.py`: nova lista `GENERAL_PREFIXES` (`contato@`, `contact@`, `faleconosco@`, `fale@`, `hello@`/`hi@`/`ola@`/`oi@`, `info@`/`geral@`), sempre do próprio domínio da empresa. `contact_rank` põe qualquer caixa de recrutamento antes do contato geral.
- Continua fora (lista de permissão, não de bloqueio): e-mail de pessoa (nome.sobrenome@, LGPD) e caixas de outro assunto (imprensa, suporte, vendas, privacidade/DPO, ouvidoria).
- `ContactFinder.discover` escolhe a melhor caixa entre **todas** as páginas varridas: recrutamento numa página de carreiras ganha do `contato@` do rodapé da home (antes parava na primeira página com e-mail).
- `night-shift outreach --recheck`: varre de novo o site de todas as empresas, ignorando a janela de 30 dias. Com `-n 0`, só varre, sem escrever e-mails.
- Rascunho de outreach sem destinatário ganha o e-mail assim que ele é encontrado.
- Painel: o aviso do card diz "a empresa não publica e-mail no site" em vez de "sem e-mail de RH".

## Como foi testado

- [x] `uv run ruff check .` e `uv run ruff format --check .`
- [x] `uv run pytest`: 288 passaram (novos: contato geral como reserva, ordem entre contato/hello/info, recrutamento sempre antes, 8 caixas que nunca são usadas, discover cai no contato geral, `--recheck` volta a varrer, rascunho ganha destinatário)
- [x] Rodado de verdade: `night-shift outreach --recheck -n 0` varreu os 105 sites da lista (run #19, sucesso). Achou 11 e-mails (antes era 1): NeuralMind `talentos@` e 10 de contato geral (BizCapital, Caju, Hotmart, Liqi, Maritaca AI, Neurotech, Pluggy, RD Station, Stark Bank, Vindi). Os rascunhos já escritos da BizCapital e da Caju ganharam destinatário.

## O que não foi coberto / riscos

- Caixa geral costuma ir para atendimento ou comercial; a resposta tende a ser menor que a de uma caixa de recrutamento.
- Sites que só mostram o e-mail depois de carregar JavaScript continuam sem e-mail (a varredura lê o HTML).

## Migrations

Nenhuma.

🤖 Generated with [Claude Code](https://claude.com/claude-code)
