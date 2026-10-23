"""Opt-in local desktop actions, limited to a fixed allowlist of apps (see app/agent.py).

Set ATLAS_ENABLE_DESKTOP_AGENT=true only when the backend runs on the user's own PC.
Typed actions with approval run as tasks (POST /api/tasks with an action kind);
/launch is the original direct, confirm-flag launcher.
"""
from __future__ import annotations

from typing import Literal

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from .. import agent

router = APIRouter(prefix="/api/desktop", tags=["desktop"])


class DesktopLaunchRequest(BaseModel):
    app_id: Literal["notepad", "calculator", "file_manager"]
    confirm: bool = False


@router.get("/status")
def desktop_status():
    return {**agent.status(), "notice": "Local-only. Desktop actions are disabled unless explicitly enabled on your own PC."}


@router.post("/launch")
def desktop_launch(body: DesktopLaunchRequest):
    if not agent.enabled():
        raise HTTPException(status_code=403, detail="Desktop agent is disabled. Enable it only on your own local PC.")
    if not body.confirm:
        raise HTTPException(status_code=400, detail="Explicit confirmation is required before launching an app.")
    try:
        result = agent.open_app(body.app_id)
    except agent.AgentError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.message) from None
    return {**result, "notice": "Launch request sent to the local operating system."}
