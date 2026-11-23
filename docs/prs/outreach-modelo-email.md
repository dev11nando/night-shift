## O que muda

**A nota de conexão do LinkedIn sai do outreach**: a abordagem a recrutadores no LinkedIn é feita à mão, com mensagem única. O outreach passa a ser só o e-mail (o link para buscar recrutadores da empresa no LinkedIn continua no card).

O e-mail de outreach (empresa sem vaga aberta) agora segue as **regras do candidato**, com um modelo dele como referência de estrutura e tom (não para copiar).

- `profile.yaml` ganha a seção `outreach` com `email_template` (referência) e `signature` (exemplo em `config/profile.example.yaml`; o arquivo real continua fora do git).
- Regras fixas no prompt, com ou sem modelo:
  - abrir direto com "Sou <assinatura>, ...", sem cerimônia ("Olá, equipe de recrutamento", "Prezados"…);
  - tom direto e objetivo, focado no que o candidato fez, sem floreio nem bajulação;
  - falar da experiência, não do empregador: nunca citar o nome das empresas onde trabalhou;
  - ligar a experiência à empresa-alvo com algo específico do setor ou do que ela diz de si;
  - fechar com disponibilidade para conversar e CV em anexo, e terminar com "Atenciosamente," e a assinatura.
- O modelo serve de referência: o LLM escolhe as palavras e quais experiências destacar para cada empresa. Empresa citada no modelo é tratada como exemplo.
- Validação (se falhar, o LLM tenta de novo com o motivo):
  - recusa saudação genérica no início, e-mail que não começa por "Sou <assinatura>" e e-mail que não termina com "Atenciosamente," + assinatura;
  - recusa e-mail que cite um ex-empregador (se a empresa-alvo já foi empregadora, o nome dela pode aparecer);
  - termos técnicos do modelo contam como conhecidos, e o limite de palavras acompanha o tamanho do modelo.

### CV fixo por tipo de vaga

- **Não há mais CV ajustado por vaga.** Cada vaga usa o CV fixo do seu TIPO (perfil da stack × idioma): no máximo 6 PDFs em `output/cv/`. O LLM só escreve a carta, o que deixa a etapa de documentos mais rápida (uma chamada a menos por vaga).
- Nome: `cv_<nome>_<perfil><idioma><3 dígitos>.pdf`, com perfil 1 = python, 2 = ia, 3 = java e idioma 1 = português, 2 = inglês (`domain/naming.py`). Os 3 dígitos são sorteados uma vez e mantidos (`stable_cv_name`): regerar com `night-shift cv pdf` sobrescreve o mesmo arquivo, então as vagas continuam apontando para ele. O recrutador vê só o nome; o código só faz sentido para o candidato.
- O nome vem de `Profile.short_name`: `outreach.signature` ou, sem ela, primeiro e último nome. A assinatura do e-mail usa a mesma regra.
- Vaga sem perfil próprio (por exemplo, stack sem CV) usa o perfil python, e o código do arquivo reflete o CV realmente usado.
- O card da Fila mostra o nome do arquivo no botão do CV, para identificar o tipo.

## Como foi testado

- [x] `uv run ruff check .` e `uv run ruff format --check .`
- [x] `uv run pytest`: 277 passaram (testes novos: saudação genérica, abertura e fechamento obrigatórios, ex-empregador no e-mail, regras e modelo no prompt, termos e limite pelo modelo, ex-empregador como alvo)
- [x] Rodado de verdade: e-mails gerados com o Haiku para Creditas, NeuralMind e Getnet a partir do modelo real. Todos abrem com "Sou Marcos Paixao", fecham com "Atenciosamente," e a assinatura, não citam ex-empregadores e adaptam o meio a cada empresa (crédito na Creditas, LLMs e agentes de IA na NeuralMind, transações na Getnet). Uma tentativa da Creditas passou do limite de palavras e a segunda passou. Os rascunhos que estavam na fila foram regerados com o prompt novo.
- [x] CVs: `tests/test_naming.py` (códigos, 3 dígitos com zero à esquerda, nome curto, nome estável, cópias extras apagadas) e `tests/test_documents.py` (CV gerado uma vez por tipo, duas vagas do mesmo tipo usam o mesmo arquivo, o LLM não é chamado para ajustar CV, vaga em inglês usa o CV em inglês). Rodado de verdade: `night-shift cv pdf` gerou os 6 CVs em `output/cv/`, todos com 1 página; as 9 vagas com documentos passaram a apontar para o CV do seu tipo e as pastas por vaga foram apagadas.
- [x] `night-shift db upgrade` no banco real: coluna `linkedin_note` removida, os 23 rascunhos intactos; a página Outreach abre (200) sem a nota.

## O que não foi coberto / riscos

- Não há checagem automática de que o e-mail não cita outras empresas do mercado (por exemplo, a do modelo); o prompt pede para tratar a empresa do modelo como exemplo, e nas amostras isso não aconteceu.

## Migrations

- `a3d9e0f17b42`: remove `outreach.linkedin_note` (o downgrade recria a coluna vazia).

🤖 Generated with [Claude Code](https://claude.com/claude-code)
