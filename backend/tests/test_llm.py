from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)

def test_provider_catalog_does_not_expose_secrets():
    r = client.get('/api/llm/providers')
    assert r.status_code == 200
    ids = {p['id'] for p in r.json()['providers']}
    assert {'openai', 'groq', 'openrouter', 'nvidia', 'together', 'cerebras', 'fireworks', 'deepseek'} <= ids
    assert 'api_key' not in r.text

def test_chat_rejects_blank_prompt():
    r = client.post('/api/llm/chat', json={'provider':'groq','model':'example-model','api_key':'fake-key','prompt':' '})
    assert r.status_code == 422

def test_chat_rejects_unknown_provider():
    r = client.post('/api/llm/chat', json={'provider':'made-up','model':'x','api_key':'fake-key','prompt':'hello'})
    assert r.status_code == 422

def test_ollama_is_available_without_api_key():
    r = client.get('/api/llm/providers')
    providers = {p['id']: p for p in r.json()['providers']}
    assert providers['ollama']['key_required'] is False


def test_cloud_provider_requires_api_key():
    r = client.post('/api/llm/chat', json={'provider':'groq','model':'some-model','prompt':'hello'})
    assert r.status_code == 422


def test_blank_prompt_is_rejected_before_network_call():
    r = client.post('/api/llm/chat', json={'provider':'groq','model':'some-model','api_key':'fake-key','prompt':'   '})
    assert r.status_code == 422


def test_chat_uses_fixed_provider_endpoint_and_returns_answer(monkeypatch):
    """Exercise the real route while replacing only the outbound network client."""
    from app import main as main_module

    calls = {}

    class FakeResponse:
        status_code = 200

        @staticmethod
        def json():
            return {"choices": [{"message": {"content": "Hello from the mocked model."}}]}

    class FakeAsyncClient:
        def __init__(self, *args, **kwargs):
            calls["client_kwargs"] = kwargs

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            return False

        async def post(self, url, headers=None, json=None):
            calls.update(url=url, headers=headers, payload=json)
            return FakeResponse()

    monkeypatch.setattr(main_module.httpx, "AsyncClient", FakeAsyncClient)
    response = client.post(
        "/api/llm/chat",
        json={"provider": "groq", "model": "test-model", "api_key": "test-secret", "prompt": "hello"},
    )

    assert response.status_code == 200
    assert response.json()["answer"] == "Hello from the mocked model."
    assert calls["url"] == "https://api.groq.com/openai/v1/chat/completions"
    assert calls["headers"]["Authorization"] == "Bearer test-secret"
    assert calls["payload"]["model"] == "test-model"
    assert "test-secret" not in response.text


def test_chat_maps_provider_timeout_to_gateway_timeout(monkeypatch):
    import httpx

    from app import main as main_module

    class TimeoutAsyncClient:
        def __init__(self, *args, **kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            return False

        async def post(self, *args, **kwargs):
            raise httpx.TimeoutException("internal timeout detail")

    monkeypatch.setattr(main_module.httpx, "AsyncClient", TimeoutAsyncClient)
    response = client.post(
        "/api/llm/chat",
        json={"provider": "groq", "model": "test-model", "api_key": "test-secret", "prompt": "hello"},
    )
    assert response.status_code == 504
    assert "internal timeout detail" not in response.text


def test_ollama_status_reports_unreachable_without_leaking_details(monkeypatch):
    import httpx

    from app import main as main_module

    class UnreachableClient:
        def __init__(self, *args, **kwargs): pass
        async def __aenter__(self): return self
        async def __aexit__(self, *args): return False
        async def get(self, *args, **kwargs): raise httpx.ConnectError('private internal detail')

    monkeypatch.setattr(main_module.httpx, 'AsyncClient', UnreachableClient)
    r = client.get('/api/llm/ollama/status')
    assert r.status_code == 200
    assert r.json()['available'] is False
    assert 'private internal detail' not in r.text


def test_ollama_status_lists_models_from_fixed_local_endpoint(monkeypatch):
    from app import main as main_module
    calls = {}

    class FakeResponse:
        status_code = 200
        @staticmethod
        def json(): return {'models': [{'name': 'llama3.2:latest'}, {'name': 'qwen2.5:7b'}]}

    class FakeClient:
        def __init__(self, *args, **kwargs): pass
        async def __aenter__(self): return self
        async def __aexit__(self, *args): return False
        async def get(self, url):
            calls['url'] = url
            return FakeResponse()

    monkeypatch.setattr(main_module.httpx, 'AsyncClient', FakeClient)
    r = client.get('/api/llm/ollama/status')
    assert r.status_code == 200
    assert r.json()['models'] == ['llama3.2:latest', 'qwen2.5:7b']
    assert calls['url'] == 'http://127.0.0.1:11434/api/tags'
