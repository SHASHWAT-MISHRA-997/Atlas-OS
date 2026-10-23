"""Tasks: the original simulation planner plus real background tasks run by app/task_engine.py.

No task type executes commands, touches files or controls the desktop.
"""
from __future__ import annotations

from typing import Literal

from fastapi import APIRouter, Header, HTTPException, Query
from pydantic import BaseModel, Field, model_validator

from .. import task_engine
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
    kind: Literal["plan", "summarize_text"]
    provider: ProviderId
    model: str = Field(min_length=1, max_length=200)
    api_key: str = Field(default="", max_length=1000)
    priority: Literal[0, 1] = 0  # 1 = urgent: runs before normal queued tasks
    goal: str | None = Field(default=None, max_length=2000)
    text: str | None = Field(default=None, max_length=task_engine.MAX_INPUT_CHARS)

    @model_validator(mode="after")
    def inputs_match_kind(self):
        if self.kind == "plan" and not (self.goal or "").strip():
            raise ValueError("A plan task needs a non-blank 'goal'.")
        if self.kind == "summarize_text" and not (self.text or "").strip():
            raise ValueError("A summarize_text task needs non-blank 'text'.")
        return self

    def params(self) -> dict:
        base = {"provider": self.provider, "model": self.model.strip()}
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
async def approve_task(task_id: str, body: Approval):
    return task_engine.manager.approve(task_id, body.approval_hash)


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
