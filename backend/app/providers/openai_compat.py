"""Adapter for OpenAI-compatible chat-completions APIs (cloud providers and Ollama)."""
from __future__ import annotations

import asyncio
import json
import time
from collections.abc import AsyncIterator
from typing import Any

import httpx

from .base import ChatMessage, ChatResult, ProviderError, ProviderSpec
from .tls import tls_context

MAX_ERROR_BODY = 4096


def classify_http_error(status: int, body_text: str) -> ProviderError:
    """Map an upstream HTTP error to a safe, actionable ProviderError."""
    text = (body_text or "")[:MAX_ERROR_BODY].lower()
    if status in (401, 403):
        return ProviderError(502, "auth_failed",
                             "Provider rejected the API key or its permissions. Verify the key and account access.")
    if status == 429:
        return ProviderError(429, "rate_limited",
                             "Provider rate limit or quota reached. Wait, check billing/free-tier limits, or choose another model.")
    if status == 404 or "model_not_found" in text or ("model" in text and "not found" in text):
        return ProviderError(502, "model_not_found",
                             "The provider does not recognise this model ID. Pick a model from the list or check the provider's catalog.")
    if "context_length" in text or "maximum context" in text or "context window" in text:
        return ProviderError(400, "context_too_long",
                             "The conversation is too long for this model's context window. Clear older turns or pick a larger-context model.")
    if "out of memory" in text or "requires more system memory" in text or "cuda error" in text:
        return ProviderError(502, "out_of_memory",
                             "The model ran out of memory on the machine running it. Try a smaller model or close other GPU/RAM-heavy apps.")
    return ProviderError(502, "provider_http_error",
                         f"Provider returned HTTP {status}. Verify the model ID and provider availability.")


class OpenAICompatibleClient:
    def __init__(self, spec: ProviderSpec, api_key: str = "", connect_retries: int = 2):
        self.spec = spec
        self.api_key = api_key
        self.connect_retries = connect_retries

    # -- helpers -----------------------------------------------------------
    def _headers(self) -> dict[str, str]:
        headers = {"Content-Type": "application/json"}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
        return headers

    def _timeout(self) -> httpx.Timeout:
        # Local models can take a while to load into memory before the first token.
        return httpx.Timeout(120.0 if self.spec.local else 45.0, connect=10.0)

    @staticmethod
    def _payload(model: str, messages: list[ChatMessage], temperature: float,
                 max_tokens: int | None, stream: bool) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "model": model,
            "messages": [{"role": m.role, "content": m.content} for m in messages],
            "temperature": temperature,
        }
        if max_tokens:
            payload["max_tokens"] = max_tokens
        if stream:
            payload["stream"] = True
        return payload

    async def _backoff(self, attempt: int) -> None:
        await asyncio.sleep(min(2.0, 0.25 * (2 ** attempt)))

    # -- operations --------------------------------------------------------
    async def chat(self, model: str, messages: list[ChatMessage], temperature: float = 0.2,
                   max_tokens: int | None = None) -> ChatResult:
        url = self.spec.base_url + "/chat/completions"
        payload = self._payload(model, messages, temperature, max_tokens, stream=False)
        started = time.perf_counter()
        attempt = 0
        while True:
            try:
                async with httpx.AsyncClient(timeout=self._timeout(), follow_redirects=False, verify=tls_context()) as client:
                    response = await client.post(url, headers=self._headers(), json=payload)
                break
            except httpx.ConnectError:
                # Safe to retry: the request never reached the provider, so it cannot double-bill.
                if attempt >= self.connect_retries:
                    raise ProviderError(502, "unreachable", self._unreachable_message()) from None
                await self._backoff(attempt)
                attempt += 1
            except httpx.TimeoutException:
                raise ProviderError(504, "timeout", "Provider timed out. Try again or choose another model.") from None
            except httpx.RequestError:
                raise ProviderError(502, "unreachable", self._unreachable_message()) from None
        if response.status_code >= 400:
            raise classify_http_error(response.status_code, _safe_text(response))
        try:
            data = response.json()
            choice = data["choices"][0]
            answer = choice["message"]["content"]
            if not isinstance(answer, str) or not answer.strip():
                raise ValueError("empty content")
        except (ValueError, KeyError, IndexError, TypeError):
            raise ProviderError(502, "bad_response", "Provider response was not in the expected chat-completions format.") from None
        usage = data.get("usage") if isinstance(data, dict) else None
        return ChatResult(
            provider=self.spec.id,
            model=model,
            answer=answer,
            latency_ms=int((time.perf_counter() - started) * 1000),
            finish_reason=choice.get("finish_reason") if isinstance(choice, dict) else None,
            usage=_clean_usage(usage),
        )

    async def stream(self, model: str, messages: list[ChatMessage], temperature: float = 0.2,
                     max_tokens: int | None = None) -> AsyncIterator[dict[str, Any]]:
        """Yield ``{"type": "delta", "text": ...}`` events, then one ``{"type": "done", ...}``.

        Closing the generator (for example when the browser aborts the request)
        exits the ``httpx`` stream context, which closes the upstream connection.
        """
        url = self.spec.base_url + "/chat/completions"
        payload = self._payload(model, messages, temperature, max_tokens, stream=True)
        started = time.perf_counter()
        first_token_ms: int | None = None
        finish_reason: str | None = None
        usage: dict[str, int] | None = None
        attempt = 0
        while True:
            try:
                async with httpx.AsyncClient(timeout=self._timeout(), follow_redirects=False, verify=tls_context()) as client:
                    async with client.stream("POST", url, headers=self._headers(), json=payload) as response:
                        if response.status_code >= 400:
                            body = await response.aread()
                            raise classify_http_error(response.status_code, body[:MAX_ERROR_BODY].decode("utf-8", "replace"))
                        produced = False
                        async for line in response.aiter_lines():
                            line = line.strip()
                            if not line or not line.startswith("data:"):
                                continue
                            data = line[5:].strip()
                            if data == "[DONE]":
                                break
                            try:
                                chunk = json.loads(data)
                            except ValueError:
                                continue
                            if isinstance(chunk, dict) and chunk.get("error"):
                                err = chunk["error"]
                                raise classify_http_error(500, json.dumps(err) if not isinstance(err, str) else err)
                            choices = chunk.get("choices") if isinstance(chunk, dict) else None
                            if isinstance(chunk, dict) and chunk.get("usage"):
                                usage = _clean_usage(chunk["usage"])
                            if not choices:
                                continue
                            choice = choices[0] if isinstance(choices[0], dict) else {}
                            text = (choice.get("delta") or {}).get("content")
                            if choice.get("finish_reason"):
                                finish_reason = choice["finish_reason"]
                            if isinstance(text, str) and text:
                                if first_token_ms is None:
                                    first_token_ms = int((time.perf_counter() - started) * 1000)
                                produced = True
                                yield {"type": "delta", "text": text}
                        if not produced:
                            raise ProviderError(502, "bad_response", "Provider returned an empty streamed answer.")
                break
            except httpx.ConnectError:
                if attempt >= self.connect_retries:
                    raise ProviderError(502, "unreachable", self._unreachable_message()) from None
                await self._backoff(attempt)
                attempt += 1
            except httpx.TimeoutException:
                raise ProviderError(504, "timeout", "Provider timed out. Try again or choose another model.") from None
            except httpx.RequestError:
                raise ProviderError(502, "unreachable", self._unreachable_message()) from None
        yield {
            "type": "done",
            "provider": self.spec.id,
            "model": model,
            "finish_reason": finish_reason,
            "usage": usage,
            "first_token_ms": first_token_ms,
            "latency_ms": int((time.perf_counter() - started) * 1000),
        }

    async def list_models(self) -> list[str]:
        url = self.spec.base_url + "/models"
        try:
            async with httpx.AsyncClient(timeout=httpx.Timeout(15.0, connect=5.0), follow_redirects=False, verify=tls_context()) as client:
                response = await client.get(url, headers=self._headers())
        except httpx.TimeoutException:
            raise ProviderError(504, "timeout", "Provider timed out while listing models.") from None
        except httpx.RequestError:
            raise ProviderError(502, "unreachable", self._unreachable_message()) from None
        if response.status_code >= 400:
            raise classify_http_error(response.status_code, _safe_text(response))
        try:
            items = response.json()["data"]
            ids = sorted({m["id"] for m in items if isinstance(m, dict) and isinstance(m.get("id"), str)})
        except (ValueError, KeyError, TypeError):
            raise ProviderError(502, "bad_response", "Provider model list was not in the expected format.") from None
        return ids[:500]

    def _unreachable_message(self) -> str:
        if self.spec.local:
            return "Ollama is not reachable. Start Ollama (https://ollama.com/download) and try again."
        return "Could not reach the model provider. Check provider status and network access."


def _safe_text(response: Any) -> str:
    try:
        return str(response.text)[:MAX_ERROR_BODY]
    except Exception:  # noqa: BLE001 - diagnostics only, never forwarded
        return ""


def _clean_usage(usage: Any) -> dict[str, int] | None:
    if not isinstance(usage, dict):
        return None
    keys = ("prompt_tokens", "completion_tokens", "total_tokens")
    cleaned = {k: int(usage[k]) for k in keys if isinstance(usage.get(k), (int, float))}
    return cleaned or None
