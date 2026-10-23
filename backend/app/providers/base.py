"""Provider-independent types for model access.

Every adapter declares what it can do through ``Capabilities`` so the API and UI
never assume that all providers support streaming, discovery, vision or tools.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Literal

from pydantic import BaseModel, Field, field_validator

Role = Literal["system", "user", "assistant"]


class ChatMessage(BaseModel):
    role: Role
    content: str = Field(min_length=1, max_length=12000)

    @field_validator("content")
    @classmethod
    def reject_blank(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("must not be blank")
        return value


@dataclass(frozen=True)
class Capabilities:
    chat: bool = True
    streaming: bool = True
    model_discovery: bool = True
    # Not wired through ATLAS yet; reported honestly as unsupported by this build.
    vision: bool = False
    tool_calling: bool = False
    structured_output: bool = False

    def as_dict(self) -> dict[str, bool]:
        return asdict(self)


@dataclass(frozen=True)
class ProviderSpec:
    id: str
    label: str
    base_url: str  # OpenAI-compatible root, e.g. https://api.groq.com/openai/v1
    key_required: bool
    local: bool
    capabilities: Capabilities = field(default_factory=Capabilities)
    docs_url: str = ""

    @property
    def billing(self) -> str:
        return "local" if self.local else "may_bill"


@dataclass
class ChatResult:
    provider: str
    model: str
    answer: str
    latency_ms: int
    finish_reason: str | None = None
    usage: dict[str, int] | None = None


class ProviderError(Exception):
    """A classified provider failure with a message that is safe to show users.

    Provider response bodies are never forwarded: they can contain account or
    infrastructure details.
    """

    def __init__(self, status_code: int, code: str, message: str):
        super().__init__(message)
        self.status_code = status_code
        self.code = code
        self.message = message
