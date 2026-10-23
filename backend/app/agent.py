"""Desktop agent: a fixed set of typed actions on the user's own PC.

There is no shell and no free-form command. Each action has a schema, a risk
note shown to the user, and runs only as a background task that the user has
approved (see app/task_engine.py). Everything is off unless
ATLAS_ENABLE_DESKTOP_AGENT=true, which is meant for the backend running on the
user's own computer.

File actions are read-only and limited to approved folders. By default those
are Documents, Downloads and Desktop in the user's home folder; set
ATLAS_AGENT_FOLDERS="name=path;name=path" to choose others. Paths are resolved
(symlinks included) and must stay inside their folder.
"""
from __future__ import annotations

import os
import platform
import shutil
import subprocess
import time
from datetime import UTC, datetime
from pathlib import Path

from .config import get_settings

APPS = {
    "notepad": {"label": "Notepad", "commands": {"Windows": ["notepad.exe"], "Linux": ["gedit"], "Darwin": ["open", "-a", "TextEdit"]}},
    "calculator": {"label": "Calculator", "commands": {"Windows": ["calc.exe"], "Linux": ["gnome-calculator"], "Darwin": ["open", "-a", "Calculator"]}},
    "file_manager": {"label": "File Manager", "commands": {"Windows": ["explorer.exe"], "Linux": ["xdg-open", str(Path.home())], "Darwin": ["open", str(Path.home())]}},
}

MAX_LIST_ENTRIES = 500
MAX_SEARCH_RESULTS = 100
MAX_SEARCH_VISITS = 20_000
MAX_SEARCH_DEPTH = 8
SEARCH_SECONDS = 10.0


class AgentError(Exception):
    def __init__(self, status_code: int, code: str, message: str):
        super().__init__(message)
        self.status_code = status_code
        self.code = code
        self.message = message


def enabled() -> bool:
    return get_settings().enable_desktop_agent


def require_enabled() -> None:
    if not enabled():
        raise AgentError(403, "agent_disabled", "Desktop agent is disabled. Enable it only on your own PC "
                                               "(ATLAS_ENABLE_DESKTOP_AGENT=true).")


# --- folders --------------------------------------------------------------------

def approved_folders() -> dict[str, Path]:
    raw = (os.getenv("ATLAS_AGENT_FOLDERS") or "").strip()
    folders: dict[str, Path] = {}
    if raw:
        for item in raw.split(";"):
            name, sep, path = item.partition("=")
            name = name.strip().lower()
            if sep and name and path.strip() and name.replace("_", "").isalnum():
                folders[name] = Path(path.strip()).expanduser()
    else:
        home = Path.home()
        for name in ("Documents", "Downloads", "Desktop"):
            folders[name.lower()] = home / name
    return {name: path.resolve() for name, path in folders.items() if path.is_dir()}


def _resolve(folder: str, subpath: str = "") -> tuple[Path, Path]:
    roots = approved_folders()
    if folder not in roots:
        raise AgentError(422, "unknown_folder", f"'{folder}' is not an approved folder. Approved: {', '.join(sorted(roots)) or 'none'}.")
    root = roots[folder]
    target = (root / subpath).resolve() if subpath else root
    if target != root and root not in target.parents:
        raise AgentError(422, "outside_folder", "That path is outside the approved folder.")
    return root, target


def _rel(root: Path, path: Path) -> str:
    return path.relative_to(root).as_posix() or "."


def _iso(ts: float) -> str:
    return datetime.fromtimestamp(ts, UTC).isoformat(timespec="seconds")


# --- actions --------------------------------------------------------------------

def open_app(app_id: str) -> dict:
    require_enabled()
    app = APPS.get(app_id)
    if app is None:
        raise AgentError(422, "unknown_app", "That app is not on the allowlist.")
    system = platform.system()
    command = app["commands"].get(system)
    if not command:
        raise AgentError(501, "unsupported_os", f"{app['label']} is not configured for this operating system.")
    executable = command[0]
    if (system != "Windows" or not executable.lower().endswith(".exe")) and shutil.which(executable) is None:
        raise AgentError(503, "app_missing", f"{app['label']} is not installed or not on PATH.")
    try:
        # Fixed argument list from the allowlist; never shell=True, never user text.
        subprocess.Popen(command, shell=False, close_fds=True)  # noqa: S603
    except OSError:
        raise AgentError(503, "launch_failed", f"Could not launch {app['label']} on this machine.") from None
    return {"launched": True, "app_id": app_id, "label": app["label"]}


def list_folder(folder: str, subpath: str = "") -> dict:
    require_enabled()
    root, target = _resolve(folder, subpath)
    if not target.is_dir():
        raise AgentError(404, "not_a_folder", "That folder does not exist.")
    entries, total = [], 0
    with os.scandir(target) as it:
        for entry in it:
            total += 1
            if len(entries) >= MAX_LIST_ENTRIES:
                continue
            try:
                if entry.is_symlink():
                    kind, size, mtime = "link", None, None  # never follow links out of the folder
                else:
                    st = entry.stat(follow_symlinks=False)
                    kind = "folder" if entry.is_dir(follow_symlinks=False) else "file"
                    size, mtime = (None if kind == "folder" else st.st_size), _iso(st.st_mtime)
            except OSError:
                kind, size, mtime = "unreadable", None, None
            entries.append({"name": entry.name, "type": kind, "size": size, "modified": mtime})
    entries.sort(key=lambda e: (e["type"] != "folder", e["name"].lower()))
    return {"folder": folder, "path": _rel(root, target), "entries": entries, "total": total,
            "truncated": total > len(entries)}


def search_files(folder: str, query: str, subpath: str = "") -> dict:
    require_enabled()
    needle = query.strip().lower()
    if not needle:
        raise AgentError(422, "empty_query", "Search text must not be blank.")
    root, start = _resolve(folder, subpath)
    if not start.is_dir():
        raise AgentError(404, "not_a_folder", "That folder does not exist.")
    deadline = time.monotonic() + SEARCH_SECONDS
    results, visited, stopped = [], 0, None
    base_depth = len(start.parts)
    for dirpath, dirnames, filenames in os.walk(start, followlinks=False, onerror=lambda _e: None):
        here = Path(dirpath)
        dirs = set(dirnames)
        if len(here.parts) - base_depth >= MAX_SEARCH_DEPTH:
            dirnames[:] = []  # report these folders but do not descend further
        for name in sorted(dirs) + filenames:
            visited += 1
            if needle in name.lower():
                results.append({"path": _rel(root, here / name), "type": "folder" if name in dirs else "file"})
                if len(results) >= MAX_SEARCH_RESULTS:
                    stopped = "result limit"
                    break
        if stopped:
            break
        if visited >= MAX_SEARCH_VISITS:
            stopped = "visit limit"
            break
        if time.monotonic() > deadline:
            stopped = "time limit"
            break
    return {"folder": folder, "query": query.strip(), "results": results, "visited": visited, "stopped_at": stopped}


# --- registry used by the task engine and UI ----------------------------------------

ACTIONS = {
    "open_app": {"label": "Open an app", "risk": "Starts a program on this PC (allowlisted apps only)."},
    "list_folder": {"label": "List a folder", "risk": "Read-only: shows file names, sizes and dates in an approved folder."},
    "search_files": {"label": "Search file names", "risk": "Read-only: searches file and folder names in an approved folder."},
}


def describe(kind: str, params: dict) -> dict:
    """Plain-language summary shown on the approval card. Built only from validated params."""
    if kind == "open_app":
        summary = f"Open {APPS.get(params.get('app_id', ''), {}).get('label', params.get('app_id'))}"
    elif kind == "list_folder":
        summary = f"List {params.get('folder')}/{params.get('path') or ''}".rstrip("/")
    else:
        summary = f"Search '{params.get('query')}' in {params.get('folder')}/{params.get('path') or ''}".rstrip("/")
    return {"label": ACTIONS[kind]["label"], "risk": ACTIONS[kind]["risk"], "summary": summary}


def validate(kind: str, params: dict) -> None:
    """Checked when the task is created, so the user approves something that can run."""
    require_enabled()
    if kind == "open_app":
        if params.get("app_id") not in APPS:
            raise AgentError(422, "unknown_app", "That app is not on the allowlist.")
    else:
        _resolve(params.get("folder", ""), params.get("path", ""))


def run(kind: str, params: dict) -> dict:
    if kind == "open_app":
        return open_app(params["app_id"])
    if kind == "list_folder":
        return list_folder(params["folder"], params.get("path", ""))
    if kind == "search_files":
        return search_files(params["folder"], params["query"], params.get("path", ""))
    raise AgentError(422, "unknown_action", "Unknown action.")


def status() -> dict:
    on = enabled()
    return {"enabled": on, "platform": platform.system(),
            "apps": [{"id": k, "label": v["label"]} for k, v in APPS.items()],
            "folders": sorted(approved_folders()) if on else [],
            "actions": [{"kind": k, **v} for k, v in ACTIONS.items()]}
