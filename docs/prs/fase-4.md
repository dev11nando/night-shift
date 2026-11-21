## O que muda

Fase 4 do escopo (docs/ESCOPO.md §10): o night-shift **roda sozinho toda noite** e tem um
**turn-off de verdade**.

### Agendamento (`adapters/scheduler/windows_task.py`)

`night-shift schedule install --at 02:00` cria a tarefa `\NightShift\Nightly` no Agendador do Windows a partir de um XML, e não do `/TR` do `schtasks`, para poder definir:
- pasta de trabalho do projeto e `night-shift.exe run` da venv;
- `WakeToRun` (acorda o PC da suspensão), roda na bateria;
- `StartWhenAvailable` (se o PC estava desligado às 02:00, roda quando ligar);
- no máximo 3 h e uma instância por vez;
- `InteractiveToken`: roda só com o usuário logado, sem senha e sem administrador.

Também: `schedule status | remove | run-now`.

### Turn-off / turn-on (`runtime/turn_off.py`, §11.1)

`night-shift off`, o atalho "night-shift OFF" ou o botão **Desligar tudo** no painel:
1. cria `run/STOP`; o pipeline confere entre cada vaga e termina limpo;
2. espera até `turn_off.grace_seconds` (30 s);
3. mata a árvore inteira de cada processo registrado que não parou (Job Object + `psutil`);
4. descarrega o modelo do Ollama, só se ele estiver em uso;
5. desliga a tarefa agendada;
6. imprime o relatório (parou sozinho, encerrado à força, sobreviventes).

`night-shift on` tira o STOP e religa a tarefa. O painel se desliga por último, depois de mostrar o relatório.

### Robustez da execução noturna

- **Uma execução por vez**: um segundo `run/collect/rank/docs` é recusado (exit 3), e a recusa vai para o log, já que de madrugada ninguém vê o terminal.
- **Log por execução** em `logs/<data>-<comando>.log`, mantendo os 60 mais recentes.
- **Retomada**: execução que ficou `running` (PC desligado ou processo morto no meio) vira `failed` na próxima, e a nova continua de onde parou porque todas as etapas são idempotentes.
- **Atalhos** na área de trabalho: `night-shift shortcuts` cria OFF, ON e Painel (respeita área de trabalho no OneDrive).
- Painel: o Hoje mostra "Agendamento: todo dia às 02:00" e o botão Desligar tudo (com confirmação).

## Como foi testado

- [x] `uv run ruff check .` e `uv run ruff format --check .`
- [x] `uv run pytest`: 159 testes (13 novos). XML da tarefa, install/status/enable/disable/remove com `schtasks` falso; turn-off com **processos reais**: um que obedece o STOP e para sozinho, outro que ignora e é morto, sem matar o próprio processo; on; trava ignorando o painel; tee e rotação de log; execução interrompida marcada e retomada; botão e rota do painel.
- [x] **Na máquina real**:
  - `night-shift shortcuts` criou os 3 atalhos na área de trabalho;
  - `schedule install --at 02:00` criou a tarefa, e o `status` leu de volta "todo dia às 02:00" do XML real;
  - disparei a tarefa e, com ela na etapa de nota do Haiku, rodei `night-shift off`: o pipeline **parou sozinho em 7 s** entre duas vagas, o run ficou `stopped` com as 3 notas já salvas, a tarefa ficou "(desligado)" e não sobrou nenhum processo do projeto nem do Claude CLI;
  - `night-shift on` religou a tarefa; um `collect` disparado durante outra execução foi recusado e registrado em `logs/...-collect-recusado.log`;
  - a execução completa disparada pela tarefa terminou sozinha em **6 min** (17:28:52 → 17:34:49), status `success`, **sem nenhum erro**: 1.413 vagas coletadas, 30 notas do Haiku e 5 vagas com CV + carta, tudo em `logs/20261121-172852-run.log`.

## O que não foi coberto / riscos

- **"Roda sozinho 7 noites seguidas"** (critério da fase no escopo) só se confirma com o tempo; os logs em `logs/` e a tela Hoje vão mostrar.
- O primeiro `schedule run-now` logo depois de criar a tarefa não a disparou e também não deu erro; os seguintes funcionaram. Não consegui reproduzir. Se acontecer de novo, o `Start-ScheduledTask` do PowerShell é a alternativa.
- A tarefa só roda com o usuário logado (escolha para não guardar senha). PC desligado às 02:00 → roda quando ligar.
- Fora do escopo deste PR, mas visível no teste: das 38 vagas com nota, a maior é 78, então a **fila automática segue vazia** com o limiar de 85.

## Migrations

Nenhuma.

🤖 Generated with [Claude Code](https://claude.com/claude-code)
