import time

import httpx

from night_shift import __version__
from night_shift.ports import SourceError

# Genérico de propósito: não identifica o usuário para os sites.
USER_AGENT = f"Mozilla/5.0 (compatible; night-shift/{__version__})"


def make_client(transport: httpx.BaseTransport | None = None) -> httpx.Client:
    return httpx.Client(
        headers={"User-Agent": USER_AGENT, "Accept-Language": "pt-BR,pt;q=0.9,en;q=0.8"},
        timeout=httpx.Timeout(20.0),
        follow_redirects=True,
        transport=transport or httpx.HTTPTransport(retries=2),
    )


class PoliteClient:
    """Wrapper que espaça requisições ao mesmo site e converte erros em SourceError."""

    def __init__(self, client: httpx.Client, min_interval: float = 0.5) -> None:
        self._client = client
        self._min_interval = min_interval
        self._last = 0.0

    def _wait(self) -> None:
        delta = time.monotonic() - self._last
        if delta < self._min_interval:
            time.sleep(self._min_interval - delta)
        self._last = time.monotonic()

    def get(self, url: str, **params) -> httpx.Response:
        self._wait()
        try:
            resp = self._client.get(url, params=params or None)
            resp.raise_for_status()
        except httpx.HTTPError as e:
            raise SourceError(f"GET {url}: {e}") from e
        return resp

    def get_json(self, url: str, **params):
        try:
            return self.get(url, **params).json()
        except ValueError as e:
            raise SourceError(f"GET {url}: resposta não é JSON") from e
