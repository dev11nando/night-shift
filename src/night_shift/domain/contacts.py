"""Que e-mail público serve para outreach: caixas do próprio domínio da empresa. Puro (sem
rede) para dar para testar.

Ordem: primeiro a caixa de recrutamento (talentos@, vagas@, rh@...); sem ela, o contato geral
da empresa (contato@, faleconosco@, hello@, info@...). Nada fora dessas listas é usado: e-mail
de pessoa (nome.sobrenome@) nunca, mesmo publicado (LGPD), nem caixas de outro assunto
(imprensa, suporte, vendas, privacidade, ouvidoria...).
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

# Contato geral da empresa (quando não há caixa de recrutamento), do melhor para o pior.
GENERAL_PREFIXES = [
    r"contato|contatos|contact|contactus|contact-us|faleconosco|fale-conosco|fale",
    r"hello|hi|ola|oi|hey",
    r"info|informacoes|geral",
]
GENERAL_OFFSET = 10  # contato geral sempre perde para qualquer caixa de recrutamento

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


def _rank_in(local: str, prefixes: list[str]) -> int | None:
    for rank, pattern in enumerate(prefixes):
        if re.fullmatch(rf"({pattern})([._-]?(br|brasil|time|team|\d+))?", local):
            return rank
    return None


def recruiting_rank(email: str) -> int | None:
    """Posição na lista de prefixos (0 = melhor) ou None se não é caixa de recrutamento."""
    return _rank_in(email.split("@", 1)[0].lower(), RECRUITING_PREFIXES)


def contact_rank(email: str) -> int | None:
    """Recrutamento (0, 1, ...) antes do contato geral (10, 11, ...); None = não serve."""
    rank = recruiting_rank(email)
    if rank is not None:
        return rank
    general = _rank_in(email.split("@", 1)[0].lower(), GENERAL_PREFIXES)
    return None if general is None else GENERAL_OFFSET + general


def best_contact(emails: list[str], website: str) -> tuple[int, str] | None:
    """``(rank, e-mail)`` da melhor caixa do próprio domínio, ou None."""
    candidates = []
    for raw in emails:
        email = raw.strip().strip(".").lower()
        if JUNK.search(email) or not same_company(email, website):
            continue
        rank = contact_rank(email)
        if rank is not None:
            candidates.append((rank, email))
    return min(candidates) if candidates else None


def pick_contact(emails: list[str], website: str) -> str | None:
    """Melhor caixa do próprio domínio (recrutamento antes de contato geral), ou None."""
    best = best_contact(emails, website)
    return best[1] if best else None
