import json

import httpx
import pytest

from night_shift.adapters.llm.ollama import OllamaEmbedder, OllamaError, OllamaLLM
from night_shift.application.scoring import JobFit
from night_shift.ports import LLMUnavailable


def ollama(handler) -> httpx.Client:
    return httpx.Client(base_url="http://ollama", transport=httpx.MockTransport(handler))


def test_embed_batches_requests():
    calls = []

    def handler(request):
        body = json.loads(request.content)
        calls.append(body)
        return httpx.Response(200, json={"embeddings": [[1.0, 0.0]] * len(body["input"])})

    emb = OllamaEmbedder("http://ollama", "bge-m3", client=ollama(handler))
    vectors = emb.embed([f"t{i}" for i in range(5)], batch_size=2)

    assert len(vectors) == 5
    assert [len(c["input"]) for c in calls] == [2, 2, 1]
    assert calls[0]["model"] == "bge-m3"


def test_complete_json_sends_schema_and_parses():
    sent = {}

    def handler(request):
        sent.update(json.loads(request.content))
        content = json.dumps({"score": 82, "rationale": "Boa stack.", "red_flags": []})
        return httpx.Response(200, json={"message": {"role": "assistant", "content": content}})

    llm = OllamaLLM("http://ollama", "qwen3:8b", think=False, client=ollama(handler))
    fit = llm.complete_json("sys", "prompt", JobFit)

    assert fit.score == 82
    assert sent["format"]["properties"]["score"]["maximum"] == 100
    assert sent["think"] is False
    assert sent["stream"] is False


def test_think_none_is_not_sent():
    sent = {}

    def handler(request):
        sent.update(json.loads(request.content))
        content = json.dumps({"score": 1, "rationale": "x"})
        return httpx.Response(200, json={"message": {"content": content}})

    OllamaLLM("http://ollama", "m", think=None, client=ollama(handler)).complete_json(
        "s", "p", JobFit
    )
    assert "think" not in sent


def test_missing_model_is_unavailable_with_hint():
    def handler(request):
        return httpx.Response(404, json={"error": "model 'qwen3:8b' not found"})

    llm = OllamaLLM("http://ollama", "qwen3:8b", client=ollama(handler))
    with pytest.raises(LLMUnavailable, match="ollama pull qwen3:8b"):
        llm.complete_json("s", "p", JobFit)


def test_server_down_is_unavailable():
    def handler(request):
        raise httpx.ConnectError("recusado")

    with pytest.raises(LLMUnavailable):
        OllamaEmbedder("http://ollama", "bge-m3", client=ollama(handler)).embed(["x"])


def test_out_of_schema_answer_is_error():
    def handler(request):
        return httpx.Response(200, json={"message": {"content": '{"score": 500}'}})

    with pytest.raises(OllamaError, match="fora do schema"):
        OllamaLLM("http://ollama", "m", client=ollama(handler)).complete_json("s", "p", JobFit)
