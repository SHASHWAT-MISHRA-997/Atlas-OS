"""Automations: create a task on a schedule (daily, weekly, or every N hours, in this PC's local time).

An automation only *creates* the task. The task engine's rules still apply: PC actions and cloud
model tasks wait for approval every time; local model tasks run on their own. API keys are never
stored, so a cloud model task needs the server's own key for that provider. If ATLAS was off at
the scheduled time, the automation runs once when ATLAS starts again, then returns to its schedule.
"""
from __future__ import annotations

import asyncio
import contextlib
import json
import logging
import uuid
from datetime import UTC, datetime, timedelta

from . import storage, task_engine

log = logging.getLogger("atlas.automations")
MAX_AUTOMATIONS = 50
CHECK_SECONDS = 20
DAYS = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]


class AutomationError(Exception):
    def __init__(self, status: int, code: str, message: str):
        super().__init__(message)
        self.status, self.code, self.message = status, code, message


def _local(now_utc: datetime) -> datetime:
    return now_utc.astimezone()  # the PC's own time zone


def next_run(schedule: dict, after_utc: datetime) -> datetime:
    """First scheduled moment strictly after ``after_utc``, as UTC."""
    local = _local(after_utc)
    if schedule["every"] == "hours":
        return after_utc + timedelta(hours=schedule["hours"])
    hour, minute = (int(x) for x in schedule["time"].split(":"))
    candidate = local.replace(hour=hour, minute=minute, second=0, microsecond=0)
    if schedule["every"] == "day":
        while candidate <= local:
            candidate += timedelta(days=1)
    else:
        candidate += timedelta(days=(schedule["day"] - candidate.weekday()) % 7)
        while candidate <= local:
            candidate += timedelta(days=7)
    # Re-attach the zone for that date, so a daylight-saving change keeps the wall-clock time.
    return candidate.replace(tzinfo=None).astimezone().astimezone(UTC)


def describe(schedule: dict) -> str:
    if schedule["every"] == "hours":
        return f"Every {schedule['hours']} hour{'s' if schedule['hours'] != 1 else ''}"
    if schedule["every"] == "day":
        return f"Every day at {schedule['time']}"
    return f"Every {DAYS[schedule['day']]} at {schedule['time']}"


def _row(row) -> dict:
    schedule = json.loads(row["schedule"])
    return {"id": row["id"], "name": row["name"], "task": json.loads(row["task"]), "schedule": schedule,
            "schedule_text": describe(schedule), "enabled": bool(row["enabled"]), "next_run": row["next_run"],
            "last_run": row["last_run"], "last_task_id": row["last_task_id"], "last_error": row["last_error"],
            "created_at": row["created_at"]}


def list_all() -> list[dict]:
    with storage.connection() as conn:
        return [_row(r) for r in conn.execute("SELECT * FROM automations ORDER BY created_at")]


def get(automation_id: str) -> dict:
    with storage.connection() as conn:
        row = conn.execute("SELECT * FROM automations WHERE id = ?", (automation_id,)).fetchone()
    if row is None:
        raise AutomationError(404, "not_found", "No such automation.")
    return _row(row)


def create(name: str, task: dict, schedule: dict, now: datetime | None = None) -> dict:
    now = now or datetime.now(UTC)
    with storage.connection() as conn, conn:
        if conn.execute("SELECT count(*) FROM automations").fetchone()[0] >= MAX_AUTOMATIONS:
            raise AutomationError(429, "too_many", f"At most {MAX_AUTOMATIONS} automations.")
        automation_id = str(uuid.uuid4())
        conn.execute("INSERT INTO automations(id, name, task, schedule, enabled, next_run, created_at) VALUES (?, ?, ?, ?, 1, ?, ?)",
                     (automation_id, name, json.dumps(task), json.dumps(schedule),
                      next_run(schedule, now).isoformat(timespec="seconds"), storage._now()))
    return get(automation_id)


def set_enabled(automation_id: str, enabled: bool, now: datetime | None = None) -> dict:
    current = get(automation_id)
    following = next_run(current["schedule"], now or datetime.now(UTC)).isoformat(timespec="seconds") if enabled else None
    with storage.connection() as conn, conn:
        conn.execute("UPDATE automations SET enabled = ?, next_run = ? WHERE id = ?", (int(enabled), following, automation_id))
    return get(automation_id)


def delete(automation_id: str) -> None:
    with storage.connection() as conn, conn:
        if conn.execute("DELETE FROM automations WHERE id = ?", (automation_id,)).rowcount == 0:
            raise AutomationError(404, "not_found", "No such automation.")


def _submit(task: dict) -> tuple[str | None, str | None]:
    try:
        created = task_engine.manager.submit(task["kind"], task["params"], task.get("priority", 0))
        return created["id"], None
    except task_engine.TaskError as exc:
        return None, exc.message
    except Exception as exc:  # noqa: BLE001 - provider policy errors and similar are shown on the automation
        return None, getattr(exc, "message", None) or exc.__class__.__name__


def run_now(automation_id: str, now: datetime | None = None) -> dict:
    automation = get(automation_id)
    return _record(automation, now or datetime.now(UTC), reschedule=False)


def _record(automation: dict, now: datetime, reschedule: bool) -> dict:
    task_id, error = _submit(automation["task"])
    with storage.connection() as conn, conn:
        conn.execute("UPDATE automations SET last_run = ?, last_task_id = ?, last_error = ? WHERE id = ?",
                     (now.isoformat(timespec="seconds"), task_id, error, automation["id"]))
        if reschedule:
            conn.execute("UPDATE automations SET next_run = ? WHERE id = ?",
                         (next_run(automation["schedule"], now).isoformat(timespec="seconds"), automation["id"]))
    log.info("automation %s ran: task=%s error=%s", automation["id"], task_id, error)
    return get(automation["id"])


def run_due(now: datetime | None = None) -> list[dict]:
    """Create the tasks of every automation whose time has come. Missed runs collapse into one."""
    now = now or datetime.now(UTC)
    stamp = now.isoformat(timespec="seconds")
    with storage.connection() as conn:
        due = [_row(r) for r in conn.execute("SELECT * FROM automations WHERE enabled = 1 AND next_run <= ?", (stamp,))]
    return [_record(a, now, reschedule=True) for a in due]


class Scheduler:
    def __init__(self):
        self._task: asyncio.Task | None = None

    async def start(self) -> None:
        if storage.server_storage_enabled() and self._task is None:
            self._task = asyncio.create_task(self._loop(), name="atlas-automations")

    async def stop(self) -> None:
        if self._task:
            self._task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._task
            self._task = None

    async def _loop(self) -> None:
        while True:
            try:
                run_due()  # quick SQLite work; runs on the event loop because submit() enqueues there
            except Exception:  # noqa: BLE001 - keep the scheduler alive; problems show on each automation
                log.exception("automation check failed")
            await asyncio.sleep(CHECK_SECONDS)


scheduler = Scheduler()
