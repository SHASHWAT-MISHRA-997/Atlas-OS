"""Model endpoints: provider catalogue, Ollama status, model discovery, chat and streaming chat."""
from __future__ import annotations

import json
import logging
from typing import Literal

from fastapi import APIRouter, Depends
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field, field_validator, model_validator

from ..config import get_settings
from ..providers import ChatMessage, ProviderError, all_specs, build_client, ollama_status, server_key
from ..security import enforce_llm_rate_limit

log = logging.getLogger("atlas.llm")
router = APIRouter(prefix="/api/llm", tags=["llm"])

ProviderId = Literal["openai", "groq", "openrouter", "nvidia", "together", "cerebras", "fireworks", "deepseek", "ollama"]
MAX_MESSAGES = 50
MAX_TOTAL_CHARS = 48_000


class LLMChatRequest(BaseModel):
    provider: ProviderId
    model: str = Field(min_length=1, max_length=200)
    api_key: str = Field(default="", max_length=1000)
    # Either a single prompt (original API) or a structured message list.
    prompt: str | None = Field(default=None, max_length=12000)
    messages: list[ChatMessage] | None = Field(default=None, max_length=MAX_MESSAGES)
    temperature: float = Field(default=0.2, ge=0.0, le=2.0)
    max_tokens: int | None = Field(default=None, ge=1, le=8192)

    @field_validator("model")
    @classmethod
    def reject_blank_model(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("must not be blank")
        return value.strip()

    @field_validator("prompt")
    @classmethod
    def reject_blank_prompt(cls, value: str | None) -> str | None:
        if value is not None and not value.strip():
            raise ValueError("must not be blank")
        return value.strip() if value is not None else None

    @field_validator("api_key")
    @classmethod
    def normalize_api_key(cls, value: str) -> str:
        return value.strip()

    @model_validator(mode="after")
    def exactly_one_input(self):
        if (self.prompt is None) == (self.messages is None):
            raise ValueError("Provide exactly one of 'prompt' or 'messages'.")
        if self.messages is not None:
            if not self.messages:
                raise ValueError("'messages' must not be empty.")
            if self.messages[-1].role != "user":
                raise ValueError("The last message must come from the user.")
            if sum(len(m.content) for m in self.messages) > MAX_TOTAL_CHARS:
                raise ValueError(f"Conversation exceeds {MAX_TOTAL_CHARS} characters; clear older turns.")
        return self

    def to_messages(self) -> list[ChatMessage]:
        if self.messages is not None:
            return self.messages
        return [ChatMessage(role="user", content=self.prompt or "")]


class LLMChatResponse(BaseModel):
    provider: str
    model: str
    answer: str
    local: bool
    latency_ms: int
    finish_reason: str | None = None
    usage: dict[str, int] | None = None


class ModelListRequest(BaseModel):
    provider: ProviderId
    api_key: str = Field(default="", max_length=1000)


@router.get("/providers")
def llm_providers():
    """Provider presets and what each one supports in this build."""
    settings = get_settings()
    providers = []
    for spec in all_specs():
        enabled = spec.local or settings.allow_external_providers
        providers.append({
            "id": spec.id,
            "label": spec.label,
            "key_required": spec.key_required,
            "local": spec.local,
            "billing": spec.billing,
            "enabled": enabled,
            "server_key_configured": bool(server_key(spec.id)) if not spec.local else False,
            "capabilities": spec.capabilities.as_dict(),
            "docs_url": spec.docs_url,
        })
    return {
        "default_provider": "ollama",
        "external_providers_enabled": settings.allow_external_providers,
        "providers": providers,
        "note": "Model IDs, availability, pricing, and free tiers are provider-controlled and can change.",
    }


@router.get("/ollama/status")
async def get_ollama_status():
    """Check the configured Ollama service without accepting a client-supplied URL."""
    return await ollama_status()


@router.post("/models", dependencies=[Depends(enforce_llm_rate_limit)])
async def list_models(body: ModelListRequest):
    """Discover models. The key travels in the body so it never lands in URLs or access logs."""
    if body.provider == "ollama":
        status = await ollama_status()
        if not status["available"]:
            raise ProviderError(502, "unreachable", status["message"])
        return {"provider": "ollama", "models": status["models"]}
    client = build_client(body.provider, body.api_key.strip())
    return {"provider": body.provider, "models": await client.list_models()}


@router.post("/chat", response_model=LLMChatResponse, dependencies=[Depends(enforce_llm_rate_limit)])
async def llm_chat(body: LLMChatRequest):
    """One-shot chat. A request key is used for this call only and is never stored or logged."""
    client = build_client(body.provider, body.api_key)
    try:
        result = await client.chat(body.model, body.to_messages(), body.temperature, body.max_tokens)
    except ProviderError as exc:
        log.info("chat failed provider=%s model=%s code=%s", body.provider, body.model, exc.code)
        raise
    log.info("chat ok provider=%s model=%s latency_ms=%s", body.provider, body.model, result.latency_ms)
    return LLMChatResponse(provider=result.provider, model=result.model, answer=result.answer,
                           local=client.spec.local, latency_ms=result.latency_ms,
                           finish_reason=result.finish_reason, usage=result.usage)


def _sse(event: str, data: dict) -> bytes:
    return f"event: {event}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n".encode()


@router.post("/chat/stream", dependencies=[Depends(enforce_llm_rate_limit)])
async def llm_chat_stream(body: LLMChatRequest):
    """Server-sent events: ``delta`` chunks, then ``done`` or ``error``.

    Validation and policy errors are returned as normal HTTP errors before the
    stream starts. If the browser aborts the request, the server stops reading
    from the provider and closes that connection.
    """
    client = build_client(body.provider, body.api_key)
    messages = body.to_messages()

    async def events():
        yield _sse("start", {"provider": body.provider, "model": body.model, "local": client.spec.local})
        try:
            async for item in client.stream(body.model, messages, body.temperature, body.max_tokens):
                if item["type"] == "delta":
                    yield _sse("delta", {"text": item["text"]})
                else:
                    item = {k: v for k, v in item.items() if k != "type"}
                    item["local"] = client.spec.local
                    log.info("stream ok provider=%s model=%s latency_ms=%s", body.provider, body.model, item.get("latency_ms"))
                    yield _sse("done", item)
        except ProviderError as exc:
            log.info("stream failed provider=%s model=%s code=%s", body.provider, body.model, exc.code)
            yield _sse("error", {"code": exc.code, "detail": exc.message, "status": exc.status_code})

    return StreamingResponse(events(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-store", "X-Accel-Buffering": "no"})
