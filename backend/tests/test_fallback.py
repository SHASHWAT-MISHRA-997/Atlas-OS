"""Opt-in provider fallback (spec 5.5: only if explicitly configured).

Network traffic goes to ``httpx.MockTransport`` (see conftest.py): these are mocked-upstream tests.
"""
import httpx
import pytest
from fastapi.testclient import TestClient

from app.main import app
from tests.conftest import parse_sse, sse_lines

client = TestClient(app)
LOCAL = {"provider": "ollama", "model": "llama3.2:3b", "prompt": "hello", "allow_fallback": True}
OK = {"choices": [{"message": {"content": "from groq"}, "finish_reason": "stop"}]}


@pytest.fixture
def configured(monkeypatch):
    monkeypatch.setenv("ATLAS_FALLBACK_PROVIDER", "groq")
    monkeypatch.setenv("ATLAS_FALLBACK_MODEL", "llama-3.1-8b-instant")
    monkeypatch.setenv("ATLAS_GROQ_API_KEY", "gsk-server-secret")


def ollama_down(request):
    if request.url.host in ("127.0.0.1", "localhost"):
        raise httpx.ConnectError("refused")
    return httpx.Response(200, json=OK)


def test_no_fallback_unless_the_owner_configures_one(upstream):
    upstream.handler = ollama_down
    assert client.get("/api/llm/providers").json()["fallback"] is None
    r = client.post("/api/llm/chat", json=LOCAL)
    assert r.status_code == 502 and r.json()["code"] == "unreachable"
    assert all(req.url.host in ("127.0.0.1", "localhost") for req in upstream.requests)


def test_cloud_fallback_needs_a_server_key_and_cloud_allowed(upstream, monkeypatch, configured):
    monkeypatch.delenv("ATLAS_GROQ_API_KEY")
    assert client.get("/api/llm/providers").json()["fallback"] is None
    monkeypatch.setenv("ATLAS_GROQ_API_KEY", "gsk-server-secret")
    monkeypatch.setenv("ATLAS_ALLOW_EXTERNAL_PROVIDERS", "false")
    assert client.get("/api/llm/providers").json()["fallback"] is None


def test_each_request_must_opt_in(upstream, configured):
    upstream.handler = ollama_down
    fb = client.get("/api/llm/providers").json()["fallback"]
    assert fb == {"provider": "groq", "label": fb["label"], "model": "llama-3.1-8b-instant", "local": False, "billing": "may_bill"}
    r = client.post("/api/llm/chat", json={**LOCAL, "allow_fallback": False})
    assert r.status_code == 502
    assert not any(req.url.host.endswith("groq.com") for req in upstream.requests)


def test_fallback_answers_and_says_so(upstream, configured):
    upstream.handler = ollama_down
    r = client.post("/api/llm/chat", json=LOCAL)
    assert r.status_code == 200
    body = r.json()
    assert body["answer"] == "from groq" and body["provider"] == "groq" and body["local"] is False
    assert body["fallback_from"]["provider"] == "ollama" and body["fallback_from"]["code"] == "unreachable"
    assert upstream.requests[-1].headers["authorization"] == "Bearer gsk-server-secret"
    assert upstream.json_body()["model"] == "llama-3.1-8b-instant"


def test_key_and_policy_errors_never_fall_back(upstream, configured):
    upstream.handler = lambda req: httpx.Response(401, json={"error": "bad key"})
    r = client.post("/api/llm/chat", json={"provider": "openai", "model": "m", "api_key": "sk-x", "prompt": "hi", "allow_fallback": True})
    assert r.status_code == 502 and r.json()["code"] == "auth_failed"
    assert len(upstream.requests) == 1


def test_both_failing_reports_both(upstream, configured):
    def all_down(request):
        raise httpx.ConnectError("refused")
    upstream.handler = all_down
    r = client.post("/api/llm/chat", json=LOCAL)
    assert r.status_code == 502 and "fallback" in r.json()["detail"]


def test_stream_falls_back_before_any_text(upstream, configured):
    def handler(request):
        if request.url.host in ("127.0.0.1", "localhost"):
            raise httpx.ConnectError("refused")
        return httpx.Response(200, content=sse_lines("from ", "groq"), headers={"content-type": "text/event-stream"})
    upstream.handler = handler
    with client.stream("POST", "/api/llm/chat/stream", json=LOCAL) as r:
        events = parse_sse(r.read().decode())
    names = [e for e, _ in events]
    assert names[:2] == ["start", "fallback"] and names[-1] == "done"
    assert "".join(d["text"] for e, d in events if e == "delta") == "from groq"
    assert events[-1][1]["fallback_from"]["code"] == "unreachable"


def test_stream_never_mixes_two_models_in_one_answer(upstream, configured):
    class DiesMidway(httpx.AsyncByteStream):
        async def __aiter__(self):
            yield sse_lines("partial ", done=False)
            raise httpx.ReadError("connection lost")

    def handler(request):
        if request.url.host in ("127.0.0.1", "localhost"):
            return httpx.Response(200, stream=DiesMidway(), headers={"content-type": "text/event-stream"})
        return httpx.Response(200, content=sse_lines("from groq"), headers={"content-type": "text/event-stream"})
    upstream.handler = handler
    with client.stream("POST", "/api/llm/chat/stream", json=LOCAL) as r:
        events = parse_sse(r.read().decode())
    names = [e for e, _ in events]
    assert names == ["start", "delta", "error"]
    assert not any(req.url.host.endswith("groq.com") for req in upstream.requests)
