"""Shared test fixtures.

MOCK NOTICE: ``upstream`` replaces the *network transport* of httpx with
``httpx.MockTransport``. Production code runs unchanged (real httpx parsing,
streaming and error handling); only the remote provider is simulated. Results
from these tests say nothing about real provider availability or quality.
"""
import json

import httpx
import pytest

from app.security import llm_rate_limiter


@pytest.fixture(autouse=True)
def _isolate_env(monkeypatch, tmp_path):
    # Every test gets its own empty data directory; tests never touch the real user profile.
    monkeypatch.setenv("ATLAS_DATA_DIR", str(tmp_path / "atlas-data"))
    for name in ("ATLAS_ENV", "ATLAS_SERVER_STORAGE", "ATLAS_ENABLE_API_DOCS", "ATLAS_ALLOW_EXTERNAL_PROVIDERS", "ATLAS_OLLAMA_BASE_URL",
                 "ATLAS_MAX_BODY_BYTES", "ATLAS_GROQ_API_KEY", "ATLAS_OPENAI_API_KEY", "ATLAS_API_TOKEN",
                 "ATLAS_FALLBACK_PROVIDER", "ATLAS_FALLBACK_MODEL"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("ATLAS_LLM_RATE_LIMIT_PER_MINUTE", "10000")
    # Most tests exercise features, not login: they use TestClient's default host and no token.
    # tests/test_auth.py turns authentication back on and covers it end to end.
    monkeypatch.setenv("ATLAS_ALLOWED_HOSTS", "testserver")
    monkeypatch.setenv("ATLAS_AUTH_REQUIRED", "false")
    llm_rate_limiter.reset()
    yield
    llm_rate_limiter.reset()


class Upstream:
    """Records outbound requests and answers them with ``handler``."""

    def __init__(self):
        self.requests: list[httpx.Request] = []
        self.handler = lambda request: httpx.Response(500)

    def json_body(self, index: int = -1) -> dict:
        return json.loads(self.requests[index].content)


@pytest.fixture
def upstream(monkeypatch):
    up = Upstream()
    real_client = httpx.AsyncClient

    def handle(request):
        up.requests.append(request)
        return up.handler(request)

    class PatchedAsyncClient(real_client):
        def __init__(self, *args, **kwargs):
            kwargs["transport"] = httpx.MockTransport(handle)
            super().__init__(*args, **kwargs)

    monkeypatch.setattr(httpx, "AsyncClient", PatchedAsyncClient)

    async def no_backoff(self, _attempt):
        return None

    # Patch only the retry backoff (not asyncio.sleep, which is global).
    monkeypatch.setattr("app.providers.openai_compat.OpenAICompatibleClient._backoff", no_backoff)
    return up


def sse_lines(*chunks: str, done: bool = True) -> bytes:
    """Build an OpenAI-style streaming body from text chunks."""
    out = []
    for i, text in enumerate(chunks):
        finish = "stop" if i == len(chunks) - 1 else None
        out.append("data: " + json.dumps({"choices": [{"delta": {"content": text}, "finish_reason": finish}]}))
    if done:
        out.append("data: [DONE]")
    return ("\n\n".join(out) + "\n\n").encode()


def parse_sse(text: str) -> list[tuple[str, dict]]:
    events = []
    for block in text.strip().split("\n\n"):
        event, data = "message", ""
        for line in block.splitlines():
            if line.startswith("event:"):
                event = line[6:].strip()
            elif line.startswith("data:"):
                data += line[5:].strip()
        events.append((event, json.loads(data) if data else {}))
    return events
