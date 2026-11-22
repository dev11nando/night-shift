## O que muda

Lista de empresas-alvo maior (89 → 106), com foco em fintechs e empresas que usam muito Python. Só muda `config/companies.example.yaml`; a lista real (`config/companies.yaml`, fora do git) recebeu as mesmas entradas.

**Agora com job board (entram na coleta de vagas):**
- **Getnet** — Greenhouse `getnet`, 44 vagas no Brasil (inclui vagas de AI engineer)
- **Flash** — já estava na lista; agora com Lever `flashapp` (19 vagas, BR/remoto)
- **Belvo** — já estava na lista; agora com Ashby `belvo` (open finance, BR/MX)
- **RD Station** — Greenhouse `rdstation` (hoje só um banco de talentos)

**Novas, só para outreach (sem board público no Greenhouse/Lever/Ashby):**
- Fintechs e crédito: Cumbuca, Jeitto, Mobills, Justos, TerraMagna, Agrolend, Traive
- Investimentos: Hashdex, Gorila
- Tech com muito Python: Olist, Loggi, Buser, Pipefy, Nuvemshop, Alice

## Como foi testado

- [x] `uv run pytest`: 266 passaram
- [x] Rodado de verdade: `night-shift companies probe` em cerca de 170 slugs. Os 4 boards acima respondem e as vagas são do Brasil. Ficaram de fora os boards de mesmo nome que são de outras empresas, lá fora: juno, birdie, nomad, blip, warren, kamino e swap.
- [x] `load_companies` carrega o exemplo: 105 empresas, 20 com board (a contagem bruta dá 106 porque inclui a entrada comentada de exemplo)

## O que não foi coberto / riscos

- Os sites das empresas novas não foram abertos; `companies discover` avisa quando algum não responde.
- As empresas só de outreach não trazem vagas, só entram na fila de contatos.

## Migrations

Nenhuma.

🤖 Generated with [Claude Code](https://claude.com/claude-code)
