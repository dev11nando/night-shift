"""Ollama local: embeddings (``/api/embed``) e saída JSON estruturada (``/api/chat``)."""

import httpx
from pydantic import BaseModel, ValidationError

from night_shift.ports import LLMUnavailable


class OllamaError(Exception):
    pass


class _OllamaHTTP:
    def __init__(self, base_url: str, client: httpx.Client | None = None) -> None:
        # Geração local pode demorar; o timeout é por requisição, não total.
        self.client = client or httpx.Client(base_url=base_url, timeout=httpx.Timeout(300.0))

    def post(self, path: str, payload: dict) -> dict:
        try:
            resp = self.client.post(path, json=payload)
        except httpx.TransportError as e:
            raise LLMUnavailable(f"Ollama inacessível: {e}") from e
        if resp.status_code == 404 and "not found" in resp.text:
            model = payload.get("model")
            raise LLMUnavailable(f"modelo '{model}' não baixado; rode `ollama pull {model}`")
        if resp.is_error:
            raise OllamaError(f"{path} {resp.status_code}: {resp.text[:300]}")
        return resp.json()


class OllamaEmbedder:
    def __init__(self, base_url: str, model: str, *, client: httpx.Client | None = None) -> None:
        self.model = model
        self._http = _OllamaHTTP(base_url, client)

    def embed(self, texts: list[str], batch_size: int = 16) -> list[list[float]]:
        out: list[list[float]] = []
        for i in range(0, len(texts), batch_size):
            data = self._http.post(
                "/api/embed", {"model": self.model, "input": texts[i : i + batch_size]}
            )
            out += data["embeddings"]
        return out


class OllamaLLM:
    def __init__(
        self,
        base_url: str,
        model: str,
        *,
        think: bool | None = False,
        client: httpx.Client | None = None,
    ) -> None:
        self.model = model
        self.think = think
        self._http = _OllamaHTTP(base_url, client)

    def complete_json[T: BaseModel](self, system: str, prompt: str, schema: type[T]) -> T:
        payload = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": prompt},
            ],
            "format": schema.model_json_schema(),  # saída estruturada: o Ollama força o schema
            "stream": False,
            "options": {"temperature": 0},
        }
        if self.think is not None:
            payload["think"] = self.think
        data = self._http.post("/api/chat", payload)
        content = data.get("message", {}).get("content", "")
        try:
            return schema.model_validate_json(content)
        except ValidationError as e:
            raise OllamaError(f"resposta fora do schema: {content[:300]}") from e
