"""Background task engine. Real SQLite and asyncio; the model provider is mocked
with httpx.MockTransport (see conftest.py), so model quality is not tested here."""
import asyncio
import json
import time

import httpx
import pytest
from fastapi.testclient import TestClient

from app import storage
from app.main import create_app

PLAN_JSON = json.dumps({"steps": [{"title": "Collect data", "detail": "Export sales CSV."},
                                  {"title": "Build dashboard", "detail": "Chart revenue by month."}],
                        "risks": ["Data may be incomplete"]})


def chat_response(text):
    return httpx.Response(200, json={"choices": [{"message": {"content": text}, "finish_reason": "stop"}]})


@pytest.fixture
def api(upstream):
    with TestClient(create_app()) as c:
        yield c


def wait_for(api, task_id, states, timeout=10.0):
    deadline = time.time() + timeout
    while time.time() < deadline:
        task = api.get(f"/api/tasks/{task_id}").json()
        if task["state"] in states:
            return task
        time.sleep(0.02)
    raise AssertionError(f"task stayed {task['state']}, wanted {states}")


def submit(api, **kw):
    body = {"kind": "plan", "provider": "ollama", "model": "m", "goal": "Build a sales dashboard", **kw}
    r = api.post("/api/tasks", json=body)
    assert r.status_code == 202, r.text
    return r.json()


def test_plan_task_runs_through_real_states(api, upstream):
    upstream.handler = lambda req: chat_response("Here you go:\n```json\n" + PLAN_JSON + "\n```")
    task = submit(api)
    assert task["state"] == "Queued"
    done = wait_for(api, task["id"], {"Succeeded", "Failed"})
    assert done["state"] == "Succeeded", done
    assert [s["title"] for s in done["output"]["steps"]] == ["Collect data", "Build dashboard"]
    assert done["output"]["executed"] is False
    assert done["progress"] == {"done": 1, "total": 1, "note": "2 steps planned"}
    transitions = [e["message"].split(":")[0] for e in done["events"] if e["type"] == "state"]
    assert transitions == ["created as Queued", "Queued -> Planning", "Planning -> Running", "Running -> Succeeded"]
    assert done["started_at"] and done["finished_at"]
    assert api.get("/api/system/status").json()["task_runner"] == "background-engine"


def test_plan_task_fails_honestly_on_unusable_model_output(api, upstream):
    upstream.handler = lambda req: chat_response("Sure! Step one, think. Step two, do.")
    task = wait_for(api, submit(api)["id"], {"Succeeded", "Failed"})
    assert task["state"] == "Failed" and task["error"]["code"] == "invalid_plan"
    assert task["output"] is None


def test_provider_errors_fail_the_task_with_their_code(api, upstream):
    upstream.handler = lambda req: httpx.Response(404, text="model not found")
    task = wait_for(api, submit(api)["id"], {"Succeeded", "Failed"})
    assert task["error"]["code"] == "model_not_found"


def test_step_retry_on_timeout_then_success(api, upstream):
    calls = {"n": 0}

    def flaky(req):
        calls["n"] += 1
        if calls["n"] == 1:
            raise httpx.ReadTimeout("slow", request=req)
        return chat_response(PLAN_JSON)

    upstream.handler = flaky
    task = wait_for(api, submit(api)["id"], {"Succeeded", "Failed"})
    assert task["state"] == "Succeeded" and calls["n"] == 2
    assert any("step retry 1 after timeout" in e["message"] for e in task["events"])


def long_text(parts):
    return "\n\n".join(f"Paragraph {i}. " + "word " * 1000 for i in range(parts))


def test_summarize_reports_real_per_part_progress(api, upstream):
    seen = []

    def handler(req):
        content = json.loads(req.content)["messages"][-1]["content"]
        seen.append(content[:12])
        return chat_response("summary of " + content[:12])

    upstream.handler = handler
    task = submit(api, kind="summarize_text", goal=None, text=long_text(3))
    done = wait_for(api, task["id"], {"Succeeded", "Failed"})
    assert done["state"] == "Succeeded", done
    assert done["output"]["parts"] == 3
    assert done["progress"]["done"] == done["progress"]["total"] == 4  # 3 parts + 1 combine step
    assert len(seen) == 4 and seen[-1].startswith("Part 1:")
    notes = [e["message"] for e in done["events"] if e["type"] == "progress"]
    assert notes[:3] == ["0/4 summarizing part 1 of 3", "1/4 summarizing part 2 of 3", "2/4 summarizing part 3 of 3"]


def slow_handler(delay):
    async def handler(req):
        await asyncio.sleep(delay)
        return chat_response("ok " + json.loads(req.content)["messages"][-1]["content"][:8])
    return handler


def test_cancel_stops_a_running_task_promptly(api, upstream):
    upstream.handler = slow_handler(5)
    task = submit(api, kind="summarize_text", goal=None, text=long_text(4))
    wait_for(api, task["id"], {"Running"})
    started = time.time()
    r = api.post(f"/api/tasks/{task['id']}/cancel")
    assert r.status_code == 200
    done = wait_for(api, task["id"], {"Cancelled", "Failed", "Succeeded"}, timeout=3)
    assert done["state"] == "Cancelled"
    assert time.time() - started < 2
    assert len(upstream.requests) == 1  # no further parts were sent
    assert api.post(f"/api/tasks/{task['id']}/cancel").status_code == 409


def test_cancel_a_queued_task_before_it_runs(api, upstream, monkeypatch):
    upstream.handler = slow_handler(0.5)
    first = submit(api)  # holds the single "ollama" resource
    second = submit(api)
    assert api.post(f"/api/tasks/{second['id']}/cancel").json()["state"] == "Cancelled"
    wait_for(api, first["id"], {"Succeeded", "Failed"})
    assert api.get(f"/api/tasks/{second['id']}").json()["started_at"] is None


def test_pause_and_resume_between_steps(api, upstream):
    upstream.handler = slow_handler(0.2)
    task = submit(api, kind="summarize_text", goal=None, text=long_text(3))
    wait_for(api, task["id"], {"Running"})
    assert api.post(f"/api/tasks/{task['id']}/pause").json()["state"] == "Paused"
    time.sleep(0.8)
    paused = api.get(f"/api/tasks/{task['id']}").json()
    assert paused["state"] == "Paused"
    sent_while_paused = len(upstream.requests)
    assert sent_while_paused <= 2  # the in-flight step may finish, nothing new starts
    time.sleep(0.5)
    assert len(upstream.requests) == sent_while_paused
    assert api.post(f"/api/tasks/{task['id']}/resume").json()["state"] == "Running"
    assert wait_for(api, task["id"], {"Succeeded", "Failed"})["state"] == "Succeeded"
    assert api.post(f"/api/tasks/{task['id']}/resume").status_code == 409


def test_plan_tasks_cannot_be_paused(api, upstream):
    upstream.handler = slow_handler(0.3)
    task = submit(api)
    assert api.post(f"/api/tasks/{task['id']}/pause").json()["code"] == "not_pausable"


def test_local_tasks_share_one_model_at_a_time(api, upstream):
    active = {"now": 0, "max": 0}

    async def handler(req):
        active["now"] += 1
        active["max"] = max(active["max"], active["now"])
        await asyncio.sleep(0.15)
        active["now"] -= 1
        return chat_response(PLAN_JSON)

    upstream.handler = handler
    ids = [submit(api)["id"] for _ in range(3)]
    for task_id in ids:
        assert wait_for(api, task_id, {"Succeeded", "Failed"})["state"] == "Succeeded"
    assert active["max"] == 1


def test_urgent_tasks_jump_the_queue(api, upstream):
    order = []

    async def handler(req):
        order.append(json.loads(req.content)["messages"][-1]["content"])
        await asyncio.sleep(0.1)
        return chat_response(PLAN_JSON)

    upstream.handler = handler
    first = submit(api, goal="first")
    wait_for(api, first["id"], {"Planning"})
    normal = submit(api, goal="normal")
    urgent = submit(api, goal="urgent", priority=1)
    for t in (first, normal, urgent):
        wait_for(api, t["id"], {"Succeeded"})
    assert order == ["first", "urgent", "normal"]


def test_cloud_tasks_wait_for_approval_bound_to_parameters(api, upstream):
    upstream.handler = lambda req: chat_response(PLAN_JSON)
    task = submit(api, provider="groq", api_key="gsk-task-secret")
    assert task["state"] == "AwaitingApproval" and upstream.requests == []
    wrong = api.post(f"/api/tasks/{task['id']}/approve", json={"approval_hash": "0" * 64})
    assert wrong.status_code == 409 and wrong.json()["code"] == "approval_mismatch"
    ok = api.post(f"/api/tasks/{task['id']}/approve", json={"approval_hash": task["approval_hash"]})
    assert ok.json()["state"] == "Queued"
    done = wait_for(api, task["id"], {"Succeeded", "Failed"})
    assert done["state"] == "Succeeded"
    assert upstream.requests[0].headers["authorization"] == "Bearer gsk-task-secret"
    assert api.post(f"/api/tasks/{task['id']}/approve", json={"approval_hash": task["approval_hash"]}).status_code == 409
    # The key is never written to the database.
    raw = storage.db_path().read_bytes()
    wal = storage.db_path().with_name("atlas.db-wal")
    if wal.exists():
        raw += wal.read_bytes()
    assert b"gsk-task-secret" not in raw


def test_cloud_task_without_key_is_rejected_up_front(api, upstream):
    r = api.post("/api/tasks", json={"kind": "plan", "provider": "groq", "model": "m", "goal": "x"})
    assert r.status_code == 422 and r.json()["code"] == "key_required"


def test_idempotency_key_prevents_duplicate_tasks(api, upstream):
    upstream.handler = lambda req: chat_response(PLAN_JSON)
    body = {"kind": "plan", "provider": "ollama", "model": "m", "goal": "same"}
    a = api.post("/api/tasks", json=body, headers={"Idempotency-Key": "abc-1"}).json()
    b = api.post("/api/tasks", json=body, headers={"Idempotency-Key": "abc-1"}).json()
    assert a["id"] == b["id"] and b["duplicate"] is True
    clash = api.post("/api/tasks", json={**body, "goal": "different"}, headers={"Idempotency-Key": "abc-1"})
    assert clash.status_code == 409
    wait_for(api, a["id"], {"Succeeded"})
    assert len(upstream.requests) == 1


def test_task_timeout_is_enforced(api, upstream, monkeypatch):
    monkeypatch.setenv("ATLAS_TASK_TIMEOUT_SECONDS", "1")
    upstream.handler = slow_handler(5)
    task = wait_for(api, submit(api)["id"], {"Failed", "Succeeded"}, timeout=5)
    assert task["error"]["code"] == "timeout"


def test_restart_marks_unfinished_tasks_interrupted_and_retry_works(upstream):
    upstream.handler = slow_handler(10)
    with TestClient(create_app()) as api:
        task = submit(api)
        wait_for(api, task["id"], {"Planning"})
    # Leaving the context shut the engine down mid-task.
    upstream.handler = lambda req: chat_response(PLAN_JSON)
    with TestClient(create_app()) as api:
        stopped = api.get(f"/api/tasks/{task['id']}").json()
        assert stopped["state"] == "Failed" and stopped["error"]["code"] == "interrupted"
        retry = api.post(f"/api/tasks/{task['id']}/retry", json={})
        assert retry.status_code == 202
        assert wait_for(api, retry.json()["id"], {"Succeeded"})["state"] == "Succeeded"


def test_recovery_after_crash_marks_running_rows_failed(upstream):
    with storage.connection() as conn, conn:
        conn.execute("INSERT INTO tasks(id, kind, state, params, approval_hash, resource, created_at) "
                     "VALUES ('t1', 'plan', 'Running', '{\"provider\":\"ollama\",\"model\":\"m\",\"goal\":\"g\"}', 'h', 'ollama', '2026-10-23T00:00:00+00:00')")
    with TestClient(create_app()) as api:
        assert api.get("/api/tasks/t1").json()["error"]["code"] == "interrupted"


def test_input_validation(api):
    assert api.post("/api/tasks", json={"kind": "plan", "provider": "ollama", "model": "m"}).status_code == 422
    assert api.post("/api/tasks", json={"kind": "summarize_text", "provider": "ollama", "model": "m", "text": "  "}).status_code == 422
    assert api.post("/api/tasks", json={"kind": "shell", "provider": "ollama", "model": "m", "goal": "rm -rf /"}).status_code == 422
    too_long = {"kind": "summarize_text", "provider": "ollama", "model": "m", "text": "x" * 100_001}
    assert api.post("/api/tasks", content=json.dumps(too_long), headers={"content-type": "application/json"}).status_code in (413, 422)
    assert api.get("/api/tasks/nope").status_code == 404


def test_queue_is_bounded(api, upstream, monkeypatch):
    monkeypatch.setattr("app.task_engine.MAX_QUEUED", 2)
    upstream.handler = slow_handler(1)
    submit(api)
    submit(api)
    r = api.post("/api/tasks", json={"kind": "plan", "provider": "ollama", "model": "m", "goal": "x"})
    assert r.status_code == 429 and r.json()["code"] == "queue_full"


def test_list_tasks_trims_large_inputs(api, upstream):
    upstream.handler = slow_handler(0.05)
    task = submit(api, kind="summarize_text", goal=None, text="a " * 2000)
    listed = api.get("/api/tasks").json()["tasks"][0]
    assert listed["id"] == task["id"] and listed["params"]["text_chars"] == 3999
    wait_for(api, task["id"], {"Succeeded"})
