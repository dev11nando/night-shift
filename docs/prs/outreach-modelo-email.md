## O que muda

O e-mail de outreach (empresa sem vaga aberta) agora segue um **modelo escrito por você**, em vez de ser escrito do zero pelo LLM.

- `profile.yaml` ganha a seção `outreach` com `email_template` e `signature` (exemplo em `config/profile.example.yaml`; o arquivo real continua fora do git).
- Com o modelo, o prompt manda manter a abertura ("Sou ..."), os parágrafos de experiência, o fechamento e a assinatura, e reescrever só o parágrafo que liga você à empresa, com 1 ou 2 frases sobre o setor ou o que a empresa diz de si.
- Sem modelo, o e-mail continua sendo escrito do zero, mas agora abre direto por "Sou ..." e fecha com "Atenciosamente,".
- Novas checagens na validação (se falhar, o LLM tenta de novo com o motivo):
  - recusa e-mail que abre com saudação genérica ("Olá, equipe", "Prezados", "Bom dia"…);
  - recusa e-mail que cita o nome de empresas onde você trabalhou (a ideia é falar da experiência, não do empregador). Se a empresa-alvo já foi sua empregadora, o nome dela pode aparecer;
  - termos técnicos do modelo contam como conhecidos (não disparam o "cita o que não está no CV"), e o limite de palavras acompanha o tamanho do modelo.
- A assinatura checada passa a ser `outreach.signature` (padrão: o nome do perfil).

## Como foi testado

- [x] `uv run ruff check .` e `uv run ruff format --check .`
- [x] `uv run pytest`: 272 passaram (6 testes novos: saudação genérica, ex-empregador, modelo no prompt, termos e limite pelo modelo, ex-empregador como alvo)
- [x] Rodado de verdade: e-mails gerados com o Haiku para Creditas, NeuralMind e Getnet, a partir do modelo real. Os três mantiveram abertura, experiência e fechamento; não citaram ex-empregadores; só o parágrafo da empresa mudou. Na primeira versão do prompt, o parágrafo da Creditas veio longo (uma tentativa passou do limite); com o pedido de "mesmo tamanho do modelo, 1 ou 2 frases", saiu de primeira.

## O que não foi coberto / riscos

- Os 13 rascunhos que já estão na fila foram escritos com o prompt antigo; não foram regerados.
- A nota do LinkedIn não mudou: ainda pode citar uma experiência pelo nome da empresa.

## Migrations

Nenhuma.

🤖 Generated with [Claude Code](https://claude.com/claude-code)
