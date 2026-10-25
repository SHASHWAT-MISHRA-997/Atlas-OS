"""Automations: tasks created on a schedule (app/automations.py)."""
from __future__ import annotations

from typing import Literal

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field, model_validator

from .. import automations
from .tasks import TaskCreate

router = APIRouter(prefix="/api/automations", tags=["automations"])


class Schedule(BaseModel):
    every: Literal["day", "week", "hours"]
    time: str | None = Field(default=None, pattern=r"^([01]\d|2[0-3]):[0-5]\d$")
    day: int | None = Field(default=None, ge=0, le=6)  # 0 = Monday
    hours: int | None = Field(default=None, ge=1, le=24)

    @model_validator(mode="after")
    def fields_match(self):
        if self.every in ("day", "week") and not self.time:
            raise ValueError("Daily and weekly schedules need 'time' (HH:MM, this PC's local time).")
        if self.every == "week" and self.day is None:
            raise ValueError("Weekly schedules need 'day' (0 = Monday … 6 = Sunday).")
        if self.every == "hours" and not self.hours:
            raise ValueError("Hourly schedules need 'hours' (1–24).")
        return self

    def as_dict(self) -> dict:
        if self.every == "hours":
            return {"every": "hours", "hours": self.hours}
        out = {"every": self.every, "time": self.time}
        if self.every == "week":
            out["day"] = self.day
        return out


class AutomationCreate(BaseModel):
    name: str = Field(min_length=1, max_length=100)
    task: TaskCreate
    schedule: Schedule

    @model_validator(mode="after")
    def no_keys(self):
        if self.task.api_key.strip():
            raise ValueError("Automations never store API keys. Set the provider's key on the server instead.")
        if not self.name.strip():
            raise ValueError("Give the automation a name.")
        return self


class Toggle(BaseModel):
    enabled: bool


def _call(fn, *args):
    try:
        return fn(*args)
    except automations.AutomationError as exc:
        raise HTTPException(status_code=exc.status, detail=exc.message) from None


@router.get("")
def list_automations():
    return {"automations": automations.list_all(), "days": automations.DAYS}


@router.post("", status_code=201)
def create_automation(body: AutomationCreate):
    task = {"kind": body.task.kind, "params": body.task.params(), "priority": body.task.priority}
    return _call(automations.create, body.name.strip(), task, body.schedule.as_dict())


@router.patch("/{automation_id}")
def toggle_automation(automation_id: str, body: Toggle):
    return _call(automations.set_enabled, automation_id, body.enabled)


@router.post("/{automation_id}/run")
def run_automation_now(automation_id: str):
    return _call(automations.run_now, automation_id)


@router.delete("/{automation_id}", status_code=204)
def delete_automation(automation_id: str):
    _call(automations.delete, automation_id)
