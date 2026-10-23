"""Fixed provider catalogue and server-side credential lookup.

Clients choose a provider *ID*, never a URL, so the backend cannot be turned
into a proxy for arbitrary hosts (SSRF). The only configurable URL is Ollama's,
and it comes from the operator's environment, not from requests.
"""
from __future__ import annotations

import os

import httpx

from ..config import get_settings
from .base import Capabilities, ProviderError, ProviderSpec
from .openai_compat import OpenAICompatibleClient

CLOUD_PROVIDERS: dict[str, tuple[str, str, str]] = {
    # id: (label, OpenAI-compatible base URL, docs)
    "openai": ("OpenAI", "https://api.openai.com/v1", "https://platform.openai.com/docs/models"),
    "groq": ("Groq", "https://api.groq.com/openai/v1", "https://console.groq.com/docs/models"),
    "openrouter": ("OpenRouter", "https://openrouter.ai/api/v1", "https://openrouter.ai/models"),
    "nvidia": ("NVIDIA NIM", "https://integrate.api.nvidia.com/v1", "https://build.nvidia.com/models"),
    "together": ("Together AI", "https://api.together.xyz/v1", "https://docs.together.ai/docs/serverless-models"),
    "cerebras": ("Cerebras", "https://api.cerebras.ai/v1", "https://inference-docs.cerebras.ai/models/overview"),
    "fireworks": ("Fireworks AI", "https://api.fireworks.ai/inference/v1", "https://fireworks.ai/models"),
    "deepseek": ("DeepSeek", "https://api.deepseek.com/v1", "https://api-docs.deepseek.com/"),
}
PROVIDER_IDS = ("ollama", *CLOUD_PROVIDERS.keys())


def ollama_spec() -> ProviderSpec:
    root = get_settings().ollama_base_url
    return ProviderSpec(
        id="ollama",
        label="Ollama (local)",
        base_url=root + "/v1",
        key_required=False,
        local=True,
        capabilities=Capabilities(),
        docs_url="https://ollama.com/library",
    )


def get_spec(provider_id: str) -> ProviderSpec:
    if provider_id == "ollama":
        return ollama_spec()
    if provider_id not in CLOUD_PROVIDERS:
        raise ProviderError(422, "unknown_provider", "Unknown provider ID.")
    label, base_url, docs = CLOUD_PROVIDERS[provider_id]
    return ProviderSpec(id=provider_id, label=label, base_url=base_url, key_required=True, local=False,
                        capabilities=Capabilities(), docs_url=docs)


def all_specs() -> list[ProviderSpec]:
    return [get_spec(pid) for pid in PROVIDER_IDS]


def server_key_env_name(provider_id: str) -> str:
    return f"ATLAS_{provider_id.upper()}_API_KEY"


def server_key(provider_id: str) -> str:
    return (os.getenv(server_key_env_name(provider_id)) or "").strip()


def build_client(provider_id: str, request_key: str = "") -> OpenAICompatibleClient:
    """Resolve a provider client, enforcing policy before any network call."""
    spec = get_spec(provider_id)
    settings = get_settings()
    if not spec.local and not settings.allow_external_providers:
        raise ProviderError(403, "external_disabled",
                            "External providers are disabled on this ATLAS server (ATLAS_ALLOW_EXTERNAL_PROVIDERS=false).")
    key = request_key or server_key(provider_id)
    if spec.key_required and not key:
        raise ProviderError(422, "key_required", "This provider requires an API key.")
    return OpenAICompatibleClient(spec, api_key=key if not spec.local else "",
                                  connect_retries=settings.provider_connect_retries)


async def ollama_status() -> dict:
    """Probe the configured Ollama service and list installed models (never downloads any)."""
    url = get_settings().ollama_base_url + "/api/tags"
    try:
        async with httpx.AsyncClient(timeout=httpx.Timeout(3.0, connect=1.0), follow_redirects=False) as client:
            response = await client.get(url)
    except httpx.TimeoutException:
        return {"available": False, "reason": "timeout", "message": "Local Ollama did not respond in time."}
    except httpx.RequestError:
        return {"available": False, "reason": "unreachable", "message": "Ollama is not reachable on this machine.",
                "setup": "Install Ollama from https://ollama.com/download, start it, then pull a model, e.g. `ollama pull llama3.2:3b`."}
    if response.status_code >= 400:
        return {"available": False, "reason": "http_error", "message": "Ollama returned an error."}
    try:
        payload = response.json()
        models = payload.get("models", [])
        entries = []
        for m in models:
            if isinstance(m, dict) and isinstance(m.get("name"), str):
                details = m.get("details") if isinstance(m.get("details"), dict) else {}
                entries.append({
                    "name": m["name"],
                    "size_bytes": m.get("size") if isinstance(m.get("size"), int) else None,
                    "parameter_size": details.get("parameter_size") if isinstance(details.get("parameter_size"), str) else None,
                    "quantization": details.get("quantization_level") if isinstance(details.get("quantization_level"), str) else None,
                })
    except (ValueError, TypeError, AttributeError):
        return {"available": False, "reason": "invalid_response", "message": "Ollama returned an unexpected response."}
    names = [e["name"] for e in entries]
    message = "Local Ollama is reachable." if names else "Ollama is running but has no models. Pull one, e.g. `ollama pull llama3.2:3b`."
    return {"available": True, "models": names, "model_details": entries, "count": len(names), "message": message}
