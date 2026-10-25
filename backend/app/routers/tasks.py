"""Tasks: the original simulation planner plus real background tasks run by app/task_engine.py.

Model tasks only call the chosen model. Desktop-action tasks (see agent.ACTIONS)
run one typed action from app/agent.py after the user approves it; none runs
shell commands.
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
    kind: Literal["plan", "summarize_text", "open_app", "list_folder", "search_files", "index_documents",
                  "create_note", "create_document", "move_to_trash", "restore_from_trash", "media_key",
                  "open_url", "web_search"]
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
    name: str | None = Field(default=None, max_length=100)
    format: Literal["docx", "xlsx"] | None = None
    title: str = Field(default="", max_length=200)
    trash_id: str | None = Field(default=None, pattern=r"^[0-9a-f]{12}$")
    key: Literal["play_pause", "next", "previous", "volume_up", "volume_down", "mute"] | None = None
    url: str | None = Field(default=None, max_length=2000)
    engine: Literal["duckduckgo", "google", "bing"] = "duckduckgo"

    @model_validator(mode="after")
    def inputs_match_kind(self):
        if self.kind in agent.ACTIONS:
            if self.kind == "open_app" and not self.app_id:
                raise ValueError("An open_app task needs 'app_id'.")
            if self.kind in ("list_folder", "search_files", "index_documents", "create_note", "create_document",
                             "move_to_trash") and not self.folder:
                raise ValueError(f"A {self.kind} task needs 'folder'.")
            if self.kind in ("create_note", "create_document") and not (self.name or "").strip():
                raise ValueError(f"A {self.kind} task needs 'name'.")
            if self.kind in ("create_note", "create_document") and self.text is None:
                raise ValueError(f"A {self.kind} task needs 'text'.")
            if self.kind == "create_document" and not self.format:
                raise ValueError("A create_document task needs 'format' (docx or xlsx).")
            if self.kind == "move_to_trash" and not self.path.strip().strip("/\\"):
                raise ValueError("A move_to_trash task needs 'path' (the file).")
            if self.kind == "restore_from_trash" and not self.trash_id:
                raise ValueError("A restore_from_trash task needs 'trash_id'.")
            if self.kind == "media_key" and not self.key:
                raise ValueError("A media_key task needs 'key'.")
            if self.kind == "open_url" and not (self.url or "").strip():
                raise ValueError("An open_url task needs 'url'.")
            if self.kind == "web_search" and not (self.query or "").strip():
                raise ValueError("A web_search task needs non-blank 'query'.")
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
        if self.kind == "index_documents":
            return {"folder": self.folder}
        if self.kind in ("create_note", "create_document"):
            out = {"folder": self.folder, "path": self.path.strip().strip("/\\"), "name": (self.name or "").strip(),
                   "text": self.text or ""}
            if self.kind == "create_document":
                out.update(format=self.format, title=self.title.strip())
            return out
        if self.kind == "move_to_trash":
            return {"folder": self.folder, "path": self.path.strip().strip("/\\")}
        if self.kind == "restore_from_trash":
            return {"trash_id": self.trash_id}
        if self.kind == "media_key":
            return {"key": self.key}
        if self.kind == "open_url":
            return {"url": (self.url or "").strip()}
        if self.kind == "web_search":
            return {"query": (self.query or "").strip(), "engine": self.engine}
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
