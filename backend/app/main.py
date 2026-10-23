from pathlib import Path
from fastapi import FastAPI
from fastapi.responses import FileResponse
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field, field_validator
from typing import Literal
import httpx

CANDIDATE_ROOT = Path(__file__).resolve().parents[2]
ROOT = CANDIDATE_ROOT if (CANDIDATE_ROOT / "frontend" / "index.html").exists() else Path(__file__).resolve().parents[1]
app = FastAPI(title="ATLAS OS API", version="0.1.0", docs_url="/api/docs")

# Same-origin by default. If frontend/backend are hosted separately, replace this
# with a strict allowlist from environment configuration before production.
app.add_middleware(
    CORSMiddleware,
    allow_origins=[],
    allow_credentials=False,
    allow_methods=["GET", "POST"],
    allow_headers=["Content-Type"],
)

class PlanRequest(BaseModel):
    command: str = Field(min_length=1, max_length=2000)

class PlanResponse(BaseModel):
    mode: str
    command: str
    steps: list[str]
    notice: str

# Preset endpoints only: do not accept arbitrary URLs from clients (SSRF protection).
LLM_PROVIDERS = {
    "openai": {"label": "OpenAI", "base_url": "https://api.openai.com/v1", "key_required": True},
    "groq": {"label": "Groq", "base_url": "https://api.groq.com/openai/v1", "key_required": True},
    "openrouter": {"label": "OpenRouter", "base_url": "https://openrouter.ai/api/v1", "key_required": True},
    "nvidia": {"label": "NVIDIA NIM", "base_url": "https://integrate.api.nvidia.com/v1", "key_required": True},
    "together": {"label": "Together AI", "base_url": "https://api.together.xyz/v1", "key_required": True},
    "cerebras": {"label": "Cerebras", "base_url": "https://api.cerebras.ai/v1", "key_required": True},
    "fireworks": {"label": "Fireworks AI", "base_url": "https://api.fireworks.ai/inference/v1", "key_required": True},
    "deepseek": {"label": "DeepSeek", "base_url": "https://api.deepseek.com/v1", "key_required": True},
    "ollama": {"label": "Ollama (local)", "base_url": "http://127.0.0.1:11434/v1", "key_required": False},
}

class LLMChatRequest(BaseModel):
    provider: Literal["openai", "groq", "openrouter", "nvidia", "together", "cerebras", "fireworks", "deepseek", "ollama"]
    model: str = Field(min_length=1, max_length=200)
    api_key: str = Field(default="", max_length=1000)
    prompt: str = Field(min_length=1, max_length=12000)

    @field_validator("model", "prompt")
    @classmethod
    def reject_whitespace_only(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("must not be blank")
        return value.strip()

    @field_validator("api_key")
    @classmethod
    def normalize_api_key(cls, value: str) -> str:
        return value.strip()

class LLMChatResponse(BaseModel):
    provider: str
    model: str
    answer: str

@app.get("/api/llm/providers")
def llm_providers():
    """Provider presets using OpenAI-compatible chat-completions APIs."""
    return {"providers": [{"id": key, "label": value["label"], "key_required": value["key_required"]}
                          for key, value in LLM_PROVIDERS.items()],
            "note": "Model IDs, availability, pricing, and free tiers are provider-controlled and can change."}

@app.post("/api/llm/chat", response_model=LLMChatResponse)
async def llm_chat(body: LLMChatRequest):
    """One-shot BYOK chat. The API key is used for this request only and is not persisted."""
    from fastapi import HTTPException
    provider = LLM_PROVIDERS[body.provider]
    if provider["key_required"] and not body.api_key:
        raise HTTPException(status_code=422, detail="This provider requires an API key.")
    url = provider["base_url"] + "/chat/completions"
    payload = {"model": body.model, "messages": [{"role": "user", "content": body.prompt}], "temperature": 0.2}
    try:
        async with httpx.AsyncClient(timeout=httpx.Timeout(45.0, connect=10.0), follow_redirects=False) as client:
            response = await client.post(url, headers={**({"Authorization": f"Bearer {body.api_key}"} if body.api_key else {}), "Content-Type": "application/json"}, json=payload)
    except httpx.TimeoutException:
        raise HTTPException(status_code=504, detail="Provider timed out. Try again or choose another model.")
    except httpx.RequestError:
        raise HTTPException(status_code=502, detail="Could not reach the model provider. Check provider status and network access.")
    if response.status_code in (401, 403):
        raise HTTPException(status_code=502, detail="Provider rejected the API key or its permissions. Verify the key and account access.")
    if response.status_code == 429:
        raise HTTPException(status_code=429, detail="Provider rate limit or quota reached. Wait, check billing/free-tier limits, or choose another model.")
    if response.status_code >= 400:
        # Do not forward provider response bodies; they may contain sensitive diagnostic details.
        raise HTTPException(status_code=502, detail=f"Provider returned HTTP {response.status_code}. Verify the model ID and provider availability.")
    try:
        data = response.json()
        answer = data["choices"][0]["message"]["content"]
        if not isinstance(answer, str) or not answer.strip():
            raise ValueError("empty content")
    except (ValueError, KeyError, IndexError, TypeError):
        raise HTTPException(status_code=502, detail="Provider response was not in the expected chat-completions format.")
    return LLMChatResponse(provider=body.provider, model=body.model, answer=answer)

@app.get("/api/llm/ollama/status")
async def ollama_status():
    """Check the local Ollama service without accepting a client-supplied URL."""
    from fastapi import HTTPException
    try:
        async with httpx.AsyncClient(timeout=httpx.Timeout(3.0, connect=1.0), follow_redirects=False) as client:
            response = await client.get("http://127.0.0.1:11434/api/tags")
    except httpx.TimeoutException:
        return {"available": False, "reason": "timeout", "message": "Local Ollama did not respond in time."}
    except httpx.RequestError:
        return {"available": False, "reason": "unreachable", "message": "Ollama is not reachable on this machine."}
    if response.status_code >= 400:
        return {"available": False, "reason": "http_error", "message": "Ollama returned an error."}
    try:
        payload = response.json()
        models = payload.get("models", [])
        names = [m.get("name") for m in models if isinstance(m, dict) and isinstance(m.get("name"), str)]
    except (ValueError, TypeError):
        return {"available": False, "reason": "invalid_response", "message": "Ollama returned an unexpected response."}
    return {"available": True, "models": names, "count": len(names), "message": "Local Ollama is reachable."}



# Desktop actions are opt-in and intentionally limited to fixed, allowlisted apps.
# Set ATLAS_ENABLE_DESKTOP_AGENT=true only when running the backend on the user's own PC.
import os
import platform
import shutil
import subprocess

DESKTOP_APPS = {
    "notepad": {"label": "Notepad", "commands": {"Windows": ["notepad.exe"], "Linux": ["gedit"], "Darwin": ["open", "-a", "TextEdit"]}},
    "calculator": {"label": "Calculator", "commands": {"Windows": ["calc.exe"], "Linux": ["gnome-calculator"], "Darwin": ["open", "-a", "Calculator"]}},
    "file_manager": {"label": "File Manager", "commands": {"Windows": ["explorer.exe"], "Linux": ["xdg-open", str(Path.home())], "Darwin": ["open", str(Path.home())]}},
}

class DesktopLaunchRequest(BaseModel):
    app_id: Literal["notepad", "calculator", "file_manager"]
    confirm: bool = False

@app.get("/api/desktop/status")
def desktop_status():
    enabled = os.getenv("ATLAS_ENABLE_DESKTOP_AGENT", "false").lower() == "true"
    return {"enabled": enabled, "platform": platform.system(), "apps": [
        {"id": app_id, "label": app["label"]} for app_id, app in DESKTOP_APPS.items()
    ], "notice": "Local-only starter. Desktop actions are disabled unless explicitly enabled in the local environment."}

@app.post("/api/desktop/launch")
def desktop_launch(body: DesktopLaunchRequest):
    from fastapi import HTTPException
    if os.getenv("ATLAS_ENABLE_DESKTOP_AGENT", "false").lower() != "true":
        raise HTTPException(status_code=403, detail="Desktop agent is disabled. Enable it only on your own local PC.")
    if not body.confirm:
        raise HTTPException(status_code=400, detail="Explicit confirmation is required before launching an app.")
    app = DESKTOP_APPS[body.app_id]
    system = platform.system()
    command = app["commands"].get(system)
    if not command:
        raise HTTPException(status_code=501, detail=f"{app['label']} is not configured for this operating system.")
    # Resolve executables when possible; never use shell=True or accept arbitrary commands.
    executable = command[0]
    if system != "Windows" or not executable.lower().endswith(".exe"):
        if shutil.which(executable) is None:
            raise HTTPException(status_code=503, detail=f"{app['label']} is not installed or not on PATH.")
    try:
        subprocess.Popen(command, shell=False, close_fds=True)
    except OSError:
        raise HTTPException(status_code=503, detail=f"Could not launch {app['label']} on this machine.")
    return {"launched": True, "app_id": body.app_id, "label": app["label"], "notice": "Launch request sent to the local operating system."}


@app.get("/health")
def health():
    return {"status": "ok", "service": "atlas-os-api", "mode": "demo"}

@app.post("/api/tasks/plan", response_model=PlanResponse)
def plan_task(body: PlanRequest):
    command = body.command.strip()
    if not command:
        # Handles whitespace-only strings despite min_length validation.
        from fastapi import HTTPException
        raise HTTPException(status_code=422, detail="Command must not be blank.")
    return PlanResponse(
        mode="simulation",
        command=command,
        steps=[
            "Understand goal and constraints",
            "Assign relevant specialist roles",
            "Prepare execution and verification checklist",
            "Request permissions before real external actions",
        ],
        notice="Planning only: no files, commands, or external services were accessed.",
    )

@app.get("/", include_in_schema=False)
def frontend():
    return FileResponse(ROOT / "frontend" / "index.html")
