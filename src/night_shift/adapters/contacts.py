"""Procura, no próprio site de cada empresa, o e-mail público de recrutamento e uma frase
sobre o que a empresa faz (para personalizar o e-mail).

Educado com os sites: respeita o robots.txt, espaça as requisições e abre poucas páginas
(home, páginas de carreiras/contato linkadas na home e alguns caminhos comuns).
"""

import re
from dataclasses import dataclass, field
from html import unescape
from urllib.parse import urljoin
from urllib.robotparser import RobotFileParser

from night_shift.adapters.sources.html_text import html_to_text
from night_shift.adapters.sources.http import USER_AGENT, PoliteClient
from night_shift.domain.contacts import EMAIL, pick_contact, site_domain
from night_shift.ports import SourceError

COMMON_PATHS = [
    "/trabalhe-conosco",
    "/carreiras",
    "/careers",
    "/vagas",
    "/contato",
    "/fale-conosco",
]
LINK_HINT = re.compile(r"carreir|career|trabalhe|vagas|jobs|contat|fale-conosco|talent", re.I)
CAREERS_HINT = re.compile(r"carreir|career|trabalhe|vagas|jobs|talent", re.I)
_HREF = re.compile(r"""href=["']([^"'#]+)["']""", re.I)
_MAILTO = re.compile(r"""mailto:([^"'?\s>]+)""", re.I)
_META = re.compile(
    r"""<meta[^>]+(?:name|property)=["'](?:description|og:description)["'][^>]+content=["']([^"']+)""",
    re.I,
)
_TITLE = re.compile(r"<title[^>]*>(.*?)</title>", re.I | re.S)
MAX_PAGES = 8


@dataclass
class Discovery:
    website: str
    contact: str | None = None
    source_url: str | None = None
    careers_url: str | None = None
    about: str | None = None
    pages: list[str] = field(default_factory=list)
    error: str | None = None


def _emails(html: str) -> list[str]:
    """Em mailto:, no texto e no HTML bruto (links com e-mail sem mailto:, atributos)."""
    found = [unescape(m) for m in _MAILTO.findall(html)]
    found += EMAIL.findall(html_to_text(html))
    found += EMAIL.findall(unescape(html))
    return found


def _about(html: str) -> str | None:
    m = _META.search(html) or _TITLE.search(html)
    if not m:
        return None
    text = re.sub(r"\s+", " ", unescape(m.group(1))).strip()
    return text[:400] or None


class ContactFinder:
    def __init__(self, http: PoliteClient) -> None:
        self.http = http

    def _robots(self, base: str) -> RobotFileParser:
        rp = RobotFileParser()
        try:
            rp.parse(self.http.get(urljoin(base, "/robots.txt")).text.splitlines())
        except SourceError:
            rp.parse([])  # sem robots.txt = tudo liberado
        return rp

    def discover(self, website: str) -> Discovery:
        result = Discovery(website)
        base = website if "://" in website else f"https://{website}"
        robots = self._robots(base)
        domain = site_domain(base)

        if not robots.can_fetch(USER_AGENT, base):
            result.error = "robots.txt do site não permite"
            return result
        try:
            home = self.http.get(base).text
        except SourceError as e:
            result.error = f"site não abriu: {e}"
            return result
        result.about = _about(home)
        pages = [(base, home)]

        linked = []
        for href in _HREF.findall(home):
            if "@" in href or href.startswith(("mailto:", "tel:", "javascript:")):
                continue
            url = urljoin(base, href)
            if site_domain(url).endswith(domain) and LINK_HINT.search(url):
                linked.append(url.split("?")[0])
        candidates = list(dict.fromkeys(linked + [urljoin(base, p) for p in COMMON_PATHS]))

        for url in candidates:
            if len(pages) >= MAX_PAGES:
                break
            if not robots.can_fetch(USER_AGENT, url):
                continue
            try:
                pages.append((url, self.http.get(url).text))
            except SourceError:
                continue

        result.pages = [u for u, _ in pages]
        result.careers_url = next(
            (u for u, _ in pages[1:] if CAREERS_HINT.search(u.split("//", 1)[-1])), None
        )
        for url, html in pages:
            contact = pick_contact(_emails(html), base)
            if contact:
                result.contact, result.source_url = contact, url
                break
        return result
