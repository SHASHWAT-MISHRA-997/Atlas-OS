"""Automations: tasks created on a schedule. Model calls go to httpx.MockTransport (see conftest.py)."""
import os
import time as time_module
from datetime import UTC, datetime, timedelta

import pytest
from fastapi.testclient import TestClient

from app import automations
from app.main import create_app


@pytest.fixture
def india(monkeypatch):
    """Run the schedule maths in a fixed zone (UTC+05:30, no daylight saving)."""
    monkeypatch.setenv("TZ", "Asia/Kolkata")
    time_module.tzset()
    yield
    monkeypatch.delenv("TZ")
    time_module.tzset()


@pytest.fixture
def api(upstream, tmp_path, monkeypatch):
    monkeypatch.setenv("ATLAS_ENABLE_DESKTOP_AGENT", "true")
    monkeypatch.setenv("ATLAS_AGENT_FOLDERS", f"documents={tmp_path}")
    with TestClient(create_app()) as c:
        yield c


PLAN = {"kind": "plan", "provider": "ollama", "model": "llama3.2:3b", "goal": "Plan my week"}
DAILY = {"every": "day", "time": "07:30"}


@pytest.mark.skipif(os.name == "nt", reason="time.tzset is not available on Windows")
def test_next_run_follows_local_time(india):
    now = datetime(2026, 10, 25, 1, 0, tzinfo=UTC)  # 06:30 in India, a Sunday
    assert automations.next_run({"every": "day", "time": "07:30"}, now) == datetime(2026, 10, 25, 2, 0, tzinfo=UTC)
    assert automations.next_run({"every": "day", "time": "06:00"}, now) == datetime(2026, 10, 26, 0, 30, tzinfo=UTC)
    assert automations.next_run({"every": "week", "day": 0, "time": "09:00"}, now) == datetime(2026, 10, 26, 3, 30, tzinfo=UTC)
    assert automations.next_run({"every": "week", "day": 6, "time": "06:00"}, now) == datetime(2026, 11, 1, 0, 30, tzinfo=UTC)
    assert automations.next_run({"every": "hours", "hours": 3}, now) == now + timedelta(hours=3)


def test_create_list_pause_and_delete(api):
    r = api.post("/api/automations", json={"name": "Morning plan", "task": PLAN, "schedule": DAILY})
    assert r.status_code == 201
    a = r.json()
    assert a["schedule_text"] == "Every day at 07:30" and a["enabled"] and a["next_run"]
    assert [x["name"] for x in api.get("/api/automations").json()["automations"]] == ["Morning plan"]
    paused = api.patch(f"/api/automations/{a['id']}", json={"enabled": False}).json()
    assert paused["enabled"] is False and paused["next_run"] is None
    assert api.delete(f"/api/automations/{a['id']}").status_code == 204
    assert api.get("/api/automations").json()["automations"] == []


@pytest.mark.parametrize("schedule", [{"every": "day"}, {"every": "day", "time": "25:00"}, {"every": "week", "time": "08:00"},
                                      {"every": "hours", "hours": 0}, {"every": "minute"}])
def test_bad_schedules_are_refused(api, schedule):
    assert api.post("/api/automations", json={"name": "x", "task": PLAN, "schedule": schedule}).status_code == 422


def test_api_keys_are_never_stored(api):
    task = {**PLAN, "provider": "groq", "api_key": "gsk-secret"}
    r = api.post("/api/automations", json={"name": "x", "task": task, "schedule": DAILY})
    assert r.status_code == 422 and "gsk-secret" not in r.text


def test_due_automation_creates_a_task_and_reschedules(api, upstream):
    import httpx
    upstream.handler = lambda req: httpx.Response(200, json={"choices": [{"message": {"content": '{"steps": []}'}, "finish_reason": "stop"}]})
    a = api.post("/api/automations", json={"name": "Morning plan", "task": PLAN, "schedule": DAILY}).json()
    later = datetime.fromisoformat(a["next_run"]) + timedelta(minutes=1)
    ran = automations.run_due(later)
    assert len(ran) == 1 and ran[0]["last_task_id"] and ran[0]["last_error"] is None
    assert datetime.fromisoformat(ran[0]["next_run"]) > later
    task = api.get(f"/api/tasks/{ran[0]['last_task_id']}").json()
    assert task["kind"] == "plan" and task["params"]["goal"] == "Plan my week"
    assert automations.run_due(later) == []  # not again until the next time


def test_missed_runs_collapse_into_one(api):
    a = api.post("/api/automations", json={"name": "Hourly", "task": PLAN, "schedule": {"every": "hours", "hours": 1}}).json()
    days_later = datetime.fromisoformat(a["next_run"]) + timedelta(days=3)
    assert len(automations.run_due(days_later)) == 1
    assert automations.run_due(days_later + timedelta(minutes=5)) == []


def test_pc_actions_from_automations_still_wait_for_approval(api):
    task = {"kind": "index_documents", "folder": "documents"}
    a = api.post("/api/automations", json={"name": "Nightly index", "task": task, "schedule": DAILY}).json()
    ran = api.post(f"/api/automations/{a['id']}/run").json()
    assert api.get(f"/api/tasks/{ran['last_task_id']}").json()["state"] == "AwaitingApproval"


def test_cloud_task_without_a_server_key_records_the_problem(api):
    a = api.post("/api/automations", json={"name": "Cloud", "task": {**PLAN, "provider": "groq"}, "schedule": DAILY}).json()
    ran = api.post(f"/api/automations/{a['id']}/run").json()
    assert ran["last_task_id"] is None and "key" in ran["last_error"].lower()


def test_paused_automations_do_not_run(api):
    a = api.post("/api/automations", json={"name": "x", "task": PLAN, "schedule": DAILY}).json()
    api.patch(f"/api/automations/{a['id']}", json={"enabled": False})
    assert automations.run_due(datetime.now(UTC) + timedelta(days=2)) == []
