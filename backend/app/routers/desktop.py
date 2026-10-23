"""Opt-in local desktop actions, limited to a fixed allowlist of apps.

Set ATLAS_ENABLE_DESKTOP_AGENT=true only when the backend runs on the user's own PC.
"""
from __future__ import annotations

import platform
import shutil
import subprocess
from pathlib import Path
from typing import Literal

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from ..config import get_settings

router = APIRouter(prefix="/api/desktop", tags=["desktop"])

DESKTOP_APPS = {
    "notepad": {"label": "Notepad", "commands": {"Windows": ["notepad.exe"], "Linux": ["gedit"], "Darwin": ["open", "-a", "TextEdit"]}},
    "calculator": {"label": "Calculator", "commands": {"Windows": ["calc.exe"], "Linux": ["gnome-calculator"], "Darwin": ["open", "-a", "Calculator"]}},
    "file_manager": {"label": "File Manager", "commands": {"Windows": ["explorer.exe"], "Linux": ["xdg-open", str(Path.home())], "Darwin": ["open", str(Path.home())]}},
}


class DesktopLaunchRequest(BaseModel):
    app_id: Literal["notepad", "calculator", "file_manager"]
    confirm: bool = False


@router.get("/status")
def desktop_status():
    enabled = get_settings().enable_desktop_agent
    return {"enabled": enabled, "platform": platform.system(), "apps": [
        {"id": app_id, "label": app["label"]} for app_id, app in DESKTOP_APPS.items()
    ], "notice": "Local-only starter. Desktop actions are disabled unless explicitly enabled in the local environment."}


@router.post("/launch")
def desktop_launch(body: DesktopLaunchRequest):
    if not get_settings().enable_desktop_agent:
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
        raise HTTPException(status_code=503, detail=f"Could not launch {app['label']} on this machine.") from None
    return {"launched": True, "app_id": body.app_id, "label": app["label"], "notice": "Launch request sent to the local operating system."}
