"""Que e-mail público serve para outreach: só endereços de recrutamento do próprio domínio
da empresa. Puro (sem rede) para dar para testar.

Regra: e-mail de pessoa (nome.sobrenome@) nunca é usado, mesmo publicado. O alvo é a
caixa que a empresa publicou para receber candidaturas e currículos.
"""

import re
from urllib.parse import urlparse

EMAIL = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")

# Prefixos de caixa de recrutamento, do melhor para o pior.
RECRUITING_PREFIXES = [
    r"talentos?",
    r"recrutamento|recruiting|recruitment|recrutar",
    r"vagas?|jobs?|careers?|carreiras?|trabalheconosco|trabalhe-conosco",
    r"selecao|selection",
    r"curriculos?|cv",
    r"rh|hr|gente|people|pessoas|peopleteam|gentegestao",
]

# Coisas que aparecem em sites mas não são caixas de verdade.
JUNK = re.compile(r"\.(png|jpe?g|gif|svg|webp)$|@(sentry|example|wixpress|domain)\.", re.I)


def site_domain(url: str) -> str:
    """``https://www.nubank.com.br/x`` → ``nubank.com.br``."""
    host = (urlparse(url if "://" in url else f"https://{url}").hostname or "").lower()
    return host.removeprefix("www.")


def same_company(email: str, website: str) -> bool:
    """O e-mail é do domínio da empresa (ou de um subdomínio dele)."""
    domain = email.rsplit("@", 1)[-1].lower()
    site = site_domain(website)
    # Compara pelos dois últimos rótulos relevantes: "inter.co" x "bancointer.com.br" não
    # casa, mas "jobs.nubank.com.br" x "nubank.com.br" casa.
    return bool(site) and (domain == site or domain.endswith("." + site))


def recruiting_rank(email: str) -> int | None:
    """Posição na lista de prefixos (0 = melhor) ou None se não é caixa de recrutamento."""
    local = email.split("@", 1)[0].lower()
    for rank, pattern in enumerate(RECRUITING_PREFIXES):
        if re.fullmatch(rf"({pattern})([._-]?(br|brasil|time|team|\d+))?", local):
            return rank
    return None


def pick_contact(emails: list[str], website: str) -> str | None:
    """Melhor caixa de recrutamento do próprio domínio, ou None."""
    candidates = []
    for raw in emails:
        email = raw.strip().strip(".").lower()
        if JUNK.search(email) or not same_company(email, website):
            continue
        rank = recruiting_rank(email)
        if rank is not None:
            candidates.append((rank, email))
    return min(candidates)[1] if candidates else None
