"""HTTP hardening: headers, size limits, rate limits, docs exposure."""
import httpx
from fastapi.testclient import TestClient

from app.main import app, create_app

client = TestClient(app)


def test_security_headers_on_app_and_api():
    for path in ("/", "/health"):
        r = client.get(path)
        assert r.headers["x-content-type-options"] == "nosniff"
        assert r.headers["x-frame-options"] == "DENY"
        assert r.headers["referrer-policy"] == "no-referrer"
        assert "script-src 'self'" in r.headers["content-security-policy"]
        assert "camera=()" in r.headers["permissions-policy"]
    assert client.get("/health").headers.get("cache-control") is None
    assert client.get("/api/llm/providers").headers["cache-control"] == "no-store"


def test_frontend_has_no_inline_scripts_so_csp_can_block_them():
    html = client.get("/").text
    assert "<script>" not in html and 'src="/static/app.js"' in html
    js = client.get("/static/app.js")
    assert js.status_code == 200 and "javascript" in js.headers["content-type"]


def test_oversized_bodies_are_rejected(monkeypatch):
    monkeypatch.setenv("ATLAS_MAX_BODY_BYTES", "2048")
    r = client.post("/api/tasks/plan", content=b'{"command":"' + b"x" * 5000 + b'"}',
                    headers={"content-type": "application/json"})
    assert r.status_code == 413 and r.json()["code"] == "body_too_large"


def test_chunked_oversized_bodies_are_rejected(monkeypatch):
    monkeypatch.setenv("ATLAS_MAX_BODY_BYTES", "2048")

    def body():
        for _ in range(10):
            yield b"x" * 1000

    r = client.post("/api/tasks/plan", content=body(), headers={"content-type": "application/json"})
    assert r.status_code == 413


def test_llm_rate_limit_returns_429_with_retry_after(monkeypatch, upstream):
    monkeypatch.setenv("ATLAS_LLM_RATE_LIMIT_PER_MINUTE", "2")
    upstream.handler = lambda req: httpx.Response(200, json={"choices": [{"message": {"content": "ok"}}]})
    payload = {"provider": "ollama", "model": "m", "prompt": "hi"}
    assert client.post("/api/llm/chat", json=payload).status_code == 200
    assert client.post("/api/llm/chat", json=payload).status_code == 200
    r = client.post("/api/llm/chat", json=payload)
    assert r.status_code == 429 and int(r.headers["retry-after"]) >= 1
    assert len(upstream.requests) == 2
    # Non-model endpoints are not throttled by the model limiter.
    assert client.get("/health").status_code == 200


def test_api_docs_are_off_in_production(monkeypatch):
    monkeypatch.setenv("ATLAS_ENV", "production")
    prod = TestClient(create_app())
    assert prod.get("/api/docs").status_code == 404
    assert prod.get("/api/openapi.json").status_code == 404
    monkeypatch.setenv("ATLAS_ENABLE_API_DOCS", "true")
    assert TestClient(create_app()).get("/api/docs").status_code == 200


def test_docs_page_is_exempt_from_csp_in_development():
    r = client.get("/api/docs")
    assert r.status_code == 200 and "content-security-policy" not in r.headers


def test_system_status_reflects_real_configuration(monkeypatch, upstream):
    def down(req):
        raise httpx.ConnectError("refused", request=req)

    upstream.handler = down
    monkeypatch.setenv("ATLAS_ENABLE_DESKTOP_AGENT", "true")
    body = client.get("/api/system/status").json()
    assert body["ollama"]["available"] is False
    assert body["desktop_agent_enabled"] is True
    assert body["task_runner"] == "stopped"  # no lifespan in this client, so the engine is not running


def test_cors_does_not_allow_foreign_origins():
    r = client.options("/api/llm/chat", headers={"Origin": "https://evil.example", "Access-Control-Request-Method": "POST"})
    assert "access-control-allow-origin" not in r.headers
