"""Provider abstraction, streaming, cancellation and error handling.

All network traffic here goes to ``httpx.MockTransport`` (see conftest.py); these
are mocked-upstream tests, not live provider tests.
"""
import asyncio

import httpx
import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.providers import ChatMessage, ProviderError, build_client
from app.providers.openai_compat import classify_http_error
from tests.conftest import parse_sse, sse_lines

client = TestClient(app)
CHAT = {"provider": "groq", "model": "test-model", "api_key": "sk-test-secret", "prompt": "hello"}
OK_BODY = {"choices": [{"message": {"content": "hi there"}, "finish_reason": "stop"}],
           "usage": {"prompt_tokens": 3, "completion_tokens": 2, "total_tokens": 5}}


# --- catalogue -----------------------------------------------------------------

def test_catalogue_reports_capabilities_billing_and_local_default():
    body = client.get("/api/llm/providers").json()
    assert body["default_provider"] == "ollama"
    providers = {p["id"]: p for p in body["providers"]}
    assert providers["ollama"]["local"] is True and providers["ollama"]["billing"] == "local"
    assert providers["groq"]["billing"] == "may_bill"
    assert providers["groq"]["capabilities"]["streaming"] is True
    # Not implemented in this build, so must not be advertised.
    assert providers["groq"]["capabilities"]["vision"] is False
    assert providers["groq"]["capabilities"]["tool_calling"] is False


def test_catalogue_shows_server_key_presence_but_never_the_key(monkeypatch):
    monkeypatch.setenv("ATLAS_GROQ_API_KEY", "gsk-server-secret")
    r = client.get("/api/llm/providers")
    providers = {p["id"]: p for p in r.json()["providers"]}
    assert providers["groq"]["server_key_configured"] is True
    assert providers["openai"]["server_key_configured"] is False
    assert "gsk-server-secret" not in r.text


def test_external_providers_can_be_disabled(monkeypatch, upstream):
    monkeypatch.setenv("ATLAS_ALLOW_EXTERNAL_PROVIDERS", "false")
    providers = {p["id"]: p for p in client.get("/api/llm/providers").json()["providers"]}
    assert providers["groq"]["enabled"] is False and providers["ollama"]["enabled"] is True
    r = client.post("/api/llm/chat", json=CHAT)
    assert r.status_code == 403 and r.json()["code"] == "external_disabled"
    assert upstream.requests == []


# --- chat ------------------------------------------------------------------------

def test_chat_with_messages_forwards_roles_and_reports_metadata(upstream):
    upstream.handler = lambda req: httpx.Response(200, json=OK_BODY)
    r = client.post("/api/llm/chat", json={
        "provider": "groq", "model": "m", "api_key": "k",
        "messages": [{"role": "system", "content": "be brief"}, {"role": "user", "content": "hi"}],
    })
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["answer"] == "hi there" and body["local"] is False
    assert body["usage"] == {"prompt_tokens": 3, "completion_tokens": 2, "total_tokens": 5}
    assert isinstance(body["latency_ms"], int)
    sent = upstream.json_body()
    assert [m["role"] for m in sent["messages"]] == ["system", "user"]
    assert "stream" not in sent


def test_server_side_key_is_used_when_request_has_none(monkeypatch, upstream):
    monkeypatch.setenv("ATLAS_GROQ_API_KEY", "gsk-server-secret")
    upstream.handler = lambda req: httpx.Response(200, json=OK_BODY)
    r = client.post("/api/llm/chat", json={"provider": "groq", "model": "m", "prompt": "hi"})
    assert r.status_code == 200
    assert upstream.requests[0].headers["authorization"] == "Bearer gsk-server-secret"
    assert "gsk-server-secret" not in r.text


def test_ollama_requests_never_send_an_authorization_header(upstream):
    upstream.handler = lambda req: httpx.Response(200, json=OK_BODY)
    r = client.post("/api/llm/chat", json={"provider": "ollama", "model": "llama3.2:3b", "api_key": "leak-me", "prompt": "hi"})
    assert r.status_code == 200 and r.json()["local"] is True
    assert str(upstream.requests[0].url) == "http://127.0.0.1:11434/v1/chat/completions"
    assert "authorization" not in upstream.requests[0].headers


def test_ollama_base_url_comes_from_operator_env(monkeypatch, upstream):
    monkeypatch.setenv("ATLAS_OLLAMA_BASE_URL", "http://192.168.1.20:11434/v1/")
    upstream.handler = lambda req: httpx.Response(200, json=OK_BODY)
    client.post("/api/llm/chat", json={"provider": "ollama", "model": "m", "prompt": "hi"})
    assert str(upstream.requests[0].url) == "http://192.168.1.20:11434/v1/chat/completions"


def test_invalid_ollama_base_url_falls_back_to_loopback(monkeypatch, upstream):
    monkeypatch.setenv("ATLAS_OLLAMA_BASE_URL", "file:///etc/passwd")
    upstream.handler = lambda req: httpx.Response(200, json=OK_BODY)
    client.post("/api/llm/chat", json={"provider": "ollama", "model": "m", "prompt": "hi"})
    assert str(upstream.requests[0].url).startswith("http://127.0.0.1:11434/")


@pytest.mark.parametrize("payload", [
    {"provider": "groq", "model": "m", "api_key": "k"},  # neither prompt nor messages
    {"provider": "groq", "model": "m", "api_key": "k", "prompt": "a", "messages": [{"role": "user", "content": "b"}]},
    {"provider": "groq", "model": "m", "api_key": "k", "messages": []},
    {"provider": "groq", "model": "m", "api_key": "k", "messages": [{"role": "assistant", "content": "b"}]},
    {"provider": "groq", "model": "m", "api_key": "k", "messages": [{"role": "tool", "content": "b"}]},
    {"provider": "groq", "model": "m", "api_key": "k", "messages": [{"role": "user", "content": "x" * 12000}] * 5},
    {"provider": "groq", "model": "m", "api_key": "k", "prompt": "a", "temperature": 3},
])
def test_chat_rejects_malformed_conversations_before_network(upstream, payload):
    r = client.post("/api/llm/chat", json=payload)
    assert r.status_code == 422
    assert upstream.requests == []


def test_validation_errors_do_not_echo_api_keys():
    secret = "sk-" + "A" * 1100  # longer than the 1000-char limit
    r = client.post("/api/llm/chat", json={**CHAT, "api_key": secret})
    assert r.status_code == 422
    assert "AAAAAAAAAA" not in r.text
    assert isinstance(r.json()["detail"], str)


@pytest.mark.parametrize("status,body,code,client_status", [
    (401, "", "auth_failed", 502),
    (404, '{"error":"model \\"nope\\" not found, try pulling it first"}', "model_not_found", 502),
    (429, "", "rate_limited", 429),
    (400, '{"error":{"code":"context_length_exceeded"}}', "context_too_long", 400),
    (500, '{"error":"model requires more system memory (12 GiB) than is available"}', "out_of_memory", 502),
    (503, "internal-host-db-7 overloaded", "provider_http_error", 502),
])
def test_provider_errors_are_classified_without_leaking_bodies(upstream, status, body, code, client_status):
    upstream.handler = lambda req: httpx.Response(status, text=body)
    r = client.post("/api/llm/chat", json=CHAT)
    assert r.status_code == client_status
    assert r.json()["code"] == code
    assert "internal-host-db-7" not in r.text


def test_connect_errors_are_retried_with_a_bound(upstream):
    attempts = {"n": 0}

    def flaky(req):
        attempts["n"] += 1
        if attempts["n"] < 3:
            raise httpx.ConnectError("refused", request=req)
        return httpx.Response(200, json=OK_BODY)

    upstream.handler = flaky
    r = client.post("/api/llm/chat", json=CHAT)
    assert r.status_code == 200 and attempts["n"] == 3


def test_connect_retries_give_up_after_the_limit(upstream, monkeypatch):
    monkeypatch.setenv("ATLAS_PROVIDER_CONNECT_RETRIES", "1")

    def down(req):
        raise httpx.ConnectError("refused", request=req)

    upstream.handler = down
    r = client.post("/api/llm/chat", json=CHAT)
    assert r.status_code == 502 and r.json()["code"] == "unreachable"
    assert len(upstream.requests) == 2


def test_read_timeouts_are_not_retried(upstream):
    def slow(req):
        raise httpx.ReadTimeout("slow", request=req)

    upstream.handler = slow
    r = client.post("/api/llm/chat", json=CHAT)
    assert r.status_code == 504 and len(upstream.requests) == 1


def test_empty_answer_is_an_error_not_a_blank_reply(upstream):
    upstream.handler = lambda req: httpx.Response(200, json={"choices": [{"message": {"content": "  "}}]})
    r = client.post("/api/llm/chat", json=CHAT)
    assert r.status_code == 502 and r.json()["code"] == "bad_response"


# --- streaming -------------------------------------------------------------------

def test_stream_emits_start_deltas_and_done(upstream):
    upstream.handler = lambda req: httpx.Response(200, content=sse_lines("Hel", "lo", "!"),
                                                  headers={"content-type": "text/event-stream"})
    r = client.post("/api/llm/chat/stream", json=CHAT)
    assert r.status_code == 200
    assert r.headers["content-type"].startswith("text/event-stream")
    events = parse_sse(r.text)
    assert events[0][0] == "start" and events[0][1]["provider"] == "groq"
    assert "".join(d["text"] for e, d in events if e == "delta") == "Hello!"
    done = events[-1]
    assert done[0] == "done" and done[1]["finish_reason"] == "stop"
    assert isinstance(done[1]["first_token_ms"], int)
    assert upstream.json_body()["stream"] is True


def test_stream_reports_provider_errors_as_error_events(upstream):
    upstream.handler = lambda req: httpx.Response(404, text="model not found")
    events = parse_sse(client.post("/api/llm/chat/stream", json=CHAT).text)
    assert events[-1][0] == "error" and events[-1][1]["code"] == "model_not_found"
    assert not any(e == "delta" for e, _ in events)


def test_stream_with_no_content_is_an_error(upstream):
    upstream.handler = lambda req: httpx.Response(200, content=b"data: [DONE]\n\n")
    events = parse_sse(client.post("/api/llm/chat/stream", json=CHAT).text)
    assert events[-1][0] == "error" and events[-1][1]["code"] == "bad_response"


def test_stream_policy_errors_are_plain_http_errors(upstream):
    r = client.post("/api/llm/chat/stream", json={"provider": "groq", "model": "m", "prompt": "hi"})
    assert r.status_code == 422 and r.json()["code"] == "key_required"
    assert upstream.requests == []


class TrackingStream(httpx.AsyncByteStream):
    """An endless provider stream that records whether it was closed."""

    def __init__(self):
        self.closed = False
        self.sent = 0

    async def __aiter__(self):
        while True:
            self.sent += 1
            yield sse_lines(f"tok{self.sent} ", done=False)
            await asyncio.sleep(0)

    async def aclose(self):
        self.closed = True


def test_cancelling_a_stream_closes_the_upstream_connection(upstream):
    stream = TrackingStream()
    upstream.handler = lambda req: httpx.Response(200, stream=stream)

    async def scenario():
        provider = build_client("groq", "k")
        gen = provider.stream("m", [ChatMessage(role="user", content="hi")])
        first = await gen.__anext__()
        assert first == {"type": "delta", "text": "tok1 "}
        await gen.aclose()  # what happens when the browser aborts the request

    asyncio.run(scenario())
    assert stream.closed is True
    assert stream.sent < 5


# --- model discovery -------------------------------------------------------------

def test_cloud_model_discovery_uses_body_key_and_sorts(upstream):
    upstream.handler = lambda req: httpx.Response(200, json={"data": [{"id": "b-model"}, {"id": "a-model"}, {"bad": 1}]})
    r = client.post("/api/llm/models", json={"provider": "groq", "api_key": "k"})
    assert r.status_code == 200 and r.json()["models"] == ["a-model", "b-model"]
    assert str(upstream.requests[0].url) == "https://api.groq.com/openai/v1/models"
    assert "k" not in str(upstream.requests[0].url)


def test_ollama_model_discovery_lists_installed_models_only(upstream):
    upstream.handler = lambda req: httpx.Response(200, json={"models": [
        {"name": "qwen2.5:7b", "size": 4_700_000_000, "details": {"parameter_size": "7.6B", "quantization_level": "Q4_K_M"}}]})
    r = client.post("/api/llm/models", json={"provider": "ollama"})
    assert r.json()["models"] == ["qwen2.5:7b"]
    assert [req.method for req in upstream.requests] == ["GET"]  # never pulls/downloads
    status = client.get("/api/llm/ollama/status").json()
    assert status["model_details"][0]["parameter_size"] == "7.6B"


def test_ollama_model_discovery_reports_missing_service(upstream):
    def down(req):
        raise httpx.ConnectError("refused", request=req)

    upstream.handler = down
    r = client.post("/api/llm/models", json={"provider": "ollama"})
    assert r.status_code == 502 and r.json()["code"] == "unreachable"
    status = client.get("/api/llm/ollama/status").json()
    assert status["available"] is False and "ollama.com" in status["setup"]


def test_ollama_with_no_models_says_how_to_add_one(upstream):
    upstream.handler = lambda req: httpx.Response(200, json={"models": []})
    status = client.get("/api/llm/ollama/status").json()
    assert status["available"] is True and status["count"] == 0
    assert "ollama pull" in status["message"]


# --- classification unit ---------------------------------------------------------

def test_classifier_defaults_to_generic_message():
    err = classify_http_error(418, "teapot")
    assert isinstance(err, ProviderError) and err.code == "provider_http_error" and "418" in err.message
