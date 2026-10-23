"""Tasks: the original simulation planner plus real background tasks run by app/task_engine.py.

Model tasks only call the chosen model. Desktop-action tasks (open_app,
list_folder, search_files) run one typed action from app/agent.py after the user
approves it; none runs shell commands.
"""
from __future__ import annotations

from typing import Literal

from fastapi import APIRouter, Header, HTTPException, Query, Request
from pydantic import BaseModel, Field, model_validator

from .. import agent, task_engine
from .llm import ProviderId

router = APIRouter(prefix="/api/tasks", tags=["tasks"])


class PlanRequest(BaseModel):
    command: str = Field(min_length=1, max_length=2000)


class PlanResponse(BaseModel):
    mode: str
    command: str
    steps: list[str]
    notice: str


@router.post("/plan", response_model=PlanResponse)
def plan_task(body: PlanRequest):
    command = body.command.strip()
    if not command:
        # Handles whitespace-only strings despite min_length validation.
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


# --- real background tasks (app/task_engine.py) ---------------------------------

class TaskCreate(BaseModel):
    kind: Literal["plan", "summarize_text", "open_app", "list_folder", "search_files"]
    provider: ProviderId | None = None
    model: str | None = Field(default=None, min_length=1, max_length=200)
    api_key: str = Field(default="", max_length=1000)
    priority: Literal[0, 1] = 0  # 1 = urgent: runs before normal queued tasks
    goal: str | None = Field(default=None, max_length=2000)
    text: str | None = Field(default=None, max_length=task_engine.MAX_INPUT_CHARS)
    # desktop actions
    app_id: Literal["notepad", "calculator", "file_manager"] | None = None
    folder: str | None = Field(default=None, max_length=40, pattern=r"^[a-z0-9_]+$")
    path: str = Field(default="", max_length=500)
    query: str | None = Field(default=None, max_length=200)

    @model_validator(mode="after")
    def inputs_match_kind(self):
        if self.kind in agent.ACTIONS:
            if self.kind == "open_app" and not self.app_id:
                raise ValueError("An open_app task needs 'app_id'.")
            if self.kind in ("list_folder", "search_files") and not self.folder:
                raise ValueError(f"A {self.kind} task needs 'folder'.")
            if self.kind == "search_files" and not (self.query or "").strip():
                raise ValueError("A search_files task needs non-blank 'query'.")
            if "\x00" in self.path:
                raise ValueError("Invalid path.")
            return self
        if not self.provider or not (self.model or "").strip():
            raise ValueError(f"A {self.kind} task needs 'provider' and 'model'.")
        if self.kind == "plan" and not (self.goal or "").strip():
            raise ValueError("A plan task needs a non-blank 'goal'.")
        if self.kind == "summarize_text" and not (self.text or "").strip():
            raise ValueError("A summarize_text task needs non-blank 'text'.")
        return self

    def params(self) -> dict:
        if self.kind == "open_app":
            return {"app_id": self.app_id}
        if self.kind == "list_folder":
            return {"folder": self.folder, "path": self.path.strip().strip("/\\")}
        if self.kind == "search_files":
            return {"folder": self.folder, "path": self.path.strip().strip("/\\"), "query": (self.query or "").strip()}
        base = {"provider": self.provider, "model": (self.model or "").strip()}
        if self.kind == "plan":
            base["goal"] = (self.goal or "").strip()
        else:
            base["text"] = (self.text or "").strip()
        return base


class Approval(BaseModel):
    approval_hash: str = Field(min_length=64, max_length=64)


class RetryRequest(BaseModel):
    api_key: str = Field(default="", max_length=1000)


@router.post("", status_code=202)
async def create_task(body: TaskCreate, idempotency_key: str | None = Header(default=None, max_length=100)):
    return task_engine.manager.submit(body.kind, body.params(), body.priority, body.api_key.strip(), idempotency_key)


@router.get("")
async def list_tasks(limit: int = Query(default=50, ge=1, le=200)):
    return {"tasks": task_engine.list_tasks(limit)}


@router.get("/{task_id}")
async def get_task(task_id: str):
    return task_engine.get_task(task_id)


@router.post("/{task_id}/approve")
async def approve_task(task_id: str, body: Approval, request: Request):
    who = request.scope.get("state", {}).get("principal") or {}
    approver = f"paired device '{who.get('name')}'" if who.get("kind") == "device" else "owner"
    return task_engine.manager.approve(task_id, body.approval_hash, approver)


@router.post("/{task_id}/cancel")
async def cancel_task(task_id: str):
    return task_engine.manager.cancel(task_id)


@router.post("/{task_id}/pause")
async def pause_task(task_id: str):
    return task_engine.manager.pause(task_id)


@router.post("/{task_id}/resume")
async def resume_task(task_id: str):
    return task_engine.manager.resume(task_id)


@router.post("/{task_id}/retry", status_code=202)
async def retry_task(task_id: str, body: RetryRequest):
    return task_engine.manager.retry(task_id, body.api_key.strip())
