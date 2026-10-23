"""Runtime configuration read from environment variables.

Settings are read on every call (not cached) so tests and local operators can
change them without restarting the process. Nothing here is a secret; provider
keys are read separately in ``app.providers.registry`` and never returned.
"""
from __future__ import annotations

import os
from dataclasses import dataclass
from urllib.parse import urlparse


def _bool(name: str, default: bool) -> bool:
    raw = os.getenv(name)
    if raw is None or raw.strip() == "":
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def _int(name: str, default: int, minimum: int, maximum: int) -> int:
    raw = os.getenv(name)
    try:
        value = int(raw) if raw not in (None, "") else default
    except ValueError:
        value = default
    return max(minimum, min(maximum, value))


def _ollama_base_url() -> str:
    """Operator-configured Ollama URL. Only http(s) is accepted; never client-supplied."""
    raw = (os.getenv("ATLAS_OLLAMA_BASE_URL") or "http://127.0.0.1:11434").strip().rstrip("/")
    parsed = urlparse(raw)
    if parsed.scheme not in {"http", "https"} or not parsed.hostname or parsed.username or parsed.password:
        return "http://127.0.0.1:11434"
    if raw.endswith("/v1"):
        raw = raw[: -len("/v1")]
    return raw


@dataclass(frozen=True)
class Settings:
    env: str
    enable_api_docs: bool
    enable_desktop_agent: bool
    allow_external_providers: bool
    ollama_base_url: str
    max_body_bytes: int
    llm_rate_limit_per_minute: int
    provider_connect_retries: int

    @property
    def is_production(self) -> bool:
        return self.env == "production"


def get_settings() -> Settings:
    env = (os.getenv("ATLAS_ENV") or "development").strip().lower()
    return Settings(
        env=env,
        # Interactive API docs are on for local development and off in production
        # unless an operator turns them on deliberately.
        enable_api_docs=_bool("ATLAS_ENABLE_API_DOCS", env != "production"),
        enable_desktop_agent=_bool("ATLAS_ENABLE_DESKTOP_AGENT", False),
        allow_external_providers=_bool("ATLAS_ALLOW_EXTERNAL_PROVIDERS", True),
        ollama_base_url=_ollama_base_url(),
        max_body_bytes=_int("ATLAS_MAX_BODY_BYTES", 256 * 1024, 1024, 10 * 1024 * 1024),
        llm_rate_limit_per_minute=_int("ATLAS_LLM_RATE_LIMIT_PER_MINUTE", 30, 0, 10_000),
        provider_connect_retries=_int("ATLAS_PROVIDER_CONNECT_RETRIES", 2, 0, 5),
    )
