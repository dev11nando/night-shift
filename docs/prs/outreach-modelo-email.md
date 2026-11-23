## O que muda

O e-mail de outreach (empresa sem vaga aberta) agora segue as **regras do candidato**, com um modelo dele como referência de estrutura e tom (não para copiar).

- `profile.yaml` ganha a seção `outreach` com `email_template` (referência) e `signature` (exemplo em `config/profile.example.yaml`; o arquivo real continua fora do git).
- Regras fixas no prompt, com ou sem modelo:
  - abrir direto com "Sou <assinatura>, ...", sem cerimônia ("Olá, equipe de recrutamento", "Prezados"…);
  - tom direto e objetivo, focado no que o candidato fez, sem floreio nem bajulação;
  - falar da experiência, não do empregador: nunca citar o nome das empresas onde trabalhou (vale também para a nota do LinkedIn);
  - ligar a experiência à empresa-alvo com algo específico do setor ou do que ela diz de si;
  - fechar com disponibilidade para conversar e CV em anexo, e terminar com "Atenciosamente," e a assinatura.
- O modelo serve de referência: o LLM escolhe as palavras e quais experiências destacar para cada empresa. Empresa citada no modelo é tratada como exemplo.
- Validação (se falhar, o LLM tenta de novo com o motivo):
  - recusa saudação genérica no início, e-mail que não começa por "Sou <assinatura>" e e-mail que não termina com "Atenciosamente," + assinatura;
  - recusa nota ou e-mail que cite um ex-empregador (se a empresa-alvo já foi empregadora, o nome dela pode aparecer);
  - termos técnicos do modelo contam como conhecidos, e o limite de palavras acompanha o tamanho do modelo.

## Como foi testado

- [x] `uv run ruff check .` e `uv run ruff format --check .`
- [x] `uv run pytest`: 274 passaram (testes novos: saudação genérica, abertura e fechamento obrigatórios, ex-empregador no e-mail e na nota, regras e modelo no prompt, termos e limite pelo modelo, ex-empregador como alvo)
- [x] Rodado de verdade: e-mails gerados com o Haiku para Creditas, NeuralMind e Getnet a partir do modelo real. Todos abrem com "Sou Marcos Paixao", fecham com "Atenciosamente," e a assinatura, não citam ex-empregadores e adaptam o meio a cada empresa (crédito na Creditas, LLMs e agentes de IA na NeuralMind, transações na Getnet). Uma tentativa da Creditas passou do limite de palavras e a segunda passou. Os rascunhos que estavam na fila foram regerados com o prompt novo.

## O que não foi coberto / riscos

- Não há checagem automática de que o e-mail não cita outras empresas do mercado (por exemplo, a do modelo); o prompt pede para tratar a empresa do modelo como exemplo, e nas amostras isso não aconteceu.

## Migrations

Nenhuma.

🤖 Generated with [Claude Code](https://claude.com/claude-code)
