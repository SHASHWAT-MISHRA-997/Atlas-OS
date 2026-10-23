"""Task planning. Still simulation-only: nothing here executes work (see docs/FEATURE_MATRIX.md)."""
from __future__ import annotations

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

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
