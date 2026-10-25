"""Desktop agent: typed actions that run as approved tasks (app/agent.py).

File actions run for real against temporary folders. App launches are checked
by recording the exact process arguments (the real Notepad launch is covered on
Windows by tests/test_windows.py)."""
import os
import time

import pytest
from fastapi.testclient import TestClient

from app import agent, devices
from app.main import create_app


@pytest.fixture
def folders(tmp_path, monkeypatch):
    docs = tmp_path / "Documents"
    (docs / "college" / "sem5").mkdir(parents=True)
    (docs / "college" / "sem5" / "dbms-notes.pdf").write_bytes(b"x" * 10)
    (docs / "resume.docx").write_bytes(b"y" * 3)
    outside = tmp_path / "secret"
    outside.mkdir()
    (outside / "passwords.txt").write_text("nope")
    monkeypatch.setenv("ATLAS_AGENT_FOLDERS", f"documents={docs}")
    monkeypatch.setenv("ATLAS_ENABLE_DESKTOP_AGENT", "true")
    return docs, outside


@pytest.fixture
def api():
    with TestClient(create_app()) as c:
        yield c


def wait_for(api, task_id, states, timeout=10.0):
    deadline = time.time() + timeout
    while time.time() < deadline:
        task = api.get(f"/api/tasks/{task_id}").json()
        if task["state"] in states:
            return task
        time.sleep(0.02)
    raise AssertionError(f"task stayed {task['state']}")


def create(api, **body):
    return api.post("/api/tasks", json=body)


def approve(api, task):
    return api.post(f"/api/tasks/{task['id']}/approve", json={"approval_hash": task["approval_hash"]})


def run(api, **body):
    r = create(api, **body)
    assert r.status_code == 202, r.text
    task = r.json()
    assert approve(api, task).status_code == 200
    return wait_for(api, task["id"], {"Succeeded", "Failed"})


def test_agent_is_off_by_default(api, monkeypatch):
    monkeypatch.delenv("ATLAS_ENABLE_DESKTOP_AGENT", raising=False)
    r = create(api, kind="open_app", app_id="notepad")
    assert r.status_code == 403 and r.json()["code"] == "agent_disabled"
    assert api.get("/api/desktop/status").json()["folders"] == []


def test_every_action_waits_for_approval_and_shows_what_it_will_do(api, folders):
    task = create(api, kind="list_folder", folder="documents").json()
    assert task["state"] == "AwaitingApproval"
    assert task["action"]["summary"] == "List documents"
    assert "Read-only" in task["action"]["risk"]
    time.sleep(0.2)
    assert api.get(f"/api/tasks/{task['id']}").json()["state"] == "AwaitingApproval"  # nothing ran


def test_list_folder_after_approval(api, folders):
    done = run(api, kind="list_folder", folder="documents")
    assert done["state"] == "Succeeded", done
    entries = done["output"]["entries"]
    assert [(e["name"], e["type"]) for e in entries] == [("college", "folder"), ("resume.docx", "file")]
    assert entries[1]["size"] == 3
    assert any("approved by owner" in e["message"] for e in done["events"])


def test_search_finds_nested_file_names(api, folders):
    done = run(api, kind="search_files", folder="documents", query="DBMS")
    assert done["output"]["results"] == [{"path": "college/sem5/dbms-notes.pdf", "type": "file"}]
    assert done["output"]["stopped_at"] is None


def test_search_stops_at_result_limit(api, folders, monkeypatch):
    monkeypatch.setattr(agent, "MAX_SEARCH_RESULTS", 1)
    done = run(api, kind="search_files", folder="documents", query="e")
    assert len(done["output"]["results"]) == 1 and done["output"]["stopped_at"] == "result limit"


@pytest.mark.parametrize("path", ["../secret", "college/../../secret", "college/../.."])
def test_paths_cannot_leave_the_approved_folder(api, folders, path):
    r = create(api, kind="list_folder", folder="documents", path=path)
    assert r.status_code == 422 and r.json()["code"] == "outside_folder", r.text


def test_absolute_paths_are_treated_as_inside_the_folder(api, folders):
    task = create(api, kind="list_folder", folder="documents", path="/etc").json()
    assert task["params"]["path"] == "etc"  # leading slash stripped: means documents/etc, not /etc
    assert run(api, kind="list_folder", folder="documents", path="/etc")["error"]["code"] == "not_a_folder"


@pytest.mark.skipif(os.name == "nt", reason="symlinks need extra rights on Windows")
def test_symlinks_cannot_escape(api, folders):
    docs, outside = folders
    (docs / "shortcut").symlink_to(outside)
    r = create(api, kind="list_folder", folder="documents", path="shortcut")
    assert r.status_code == 422 and r.json()["code"] == "outside_folder"
    listing = run(api, kind="list_folder", folder="documents")["output"]["entries"]
    assert {"name": "shortcut", "type": "link", "size": None, "modified": None} in listing
    found = run(api, kind="search_files", folder="documents", query="passwords")["output"]["results"]
    assert found == []


def test_unknown_folder_and_app_are_rejected(api, folders):
    r = create(api, kind="list_folder", folder="windows")
    assert r.status_code == 422 and r.json()["code"] == "unknown_folder"
    assert create(api, kind="open_app", app_id="cmd").status_code == 422


def test_open_app_runs_only_the_allowlisted_command(api, folders, monkeypatch):
    calls = []

    class FakePopen:
        def __init__(self, args, **kw):
            calls.append((args, kw))

    monkeypatch.setattr(agent.subprocess, "Popen", FakePopen)
    monkeypatch.setattr(agent.shutil, "which", lambda name: "/usr/bin/" + name)
    monkeypatch.setattr(agent.platform, "system", lambda: "Linux")
    done = run(api, kind="open_app", app_id="calculator")
    assert done["state"] == "Succeeded" and done["output"]["label"] == "Calculator"
    assert calls == [(["gnome-calculator"], {"shell": False, "close_fds": True})]


def test_missing_app_fails_honestly(api, folders, monkeypatch):
    monkeypatch.setattr(agent.shutil, "which", lambda name: None)
    monkeypatch.setattr(agent.platform, "system", lambda: "Linux")
    done = run(api, kind="open_app", app_id="notepad")
    assert done["state"] == "Failed" and done["error"]["code"] == "app_missing"


def test_changed_parameters_need_a_new_approval(api, folders):
    task = create(api, kind="list_folder", folder="documents").json()
    r = api.post(f"/api/tasks/{task['id']}/approve", json={"approval_hash": "0" * 64})
    assert r.status_code == 409 and r.json()["code"] == "approval_mismatch"


def test_switching_agent_off_blocks_pending_approvals(api, folders, monkeypatch):
    task = create(api, kind="list_folder", folder="documents").json()
    monkeypatch.setenv("ATLAS_ENABLE_DESKTOP_AGENT", "false")
    assert approve(api, task).status_code == 403


def test_cancelled_action_never_runs(api, folders):
    task = create(api, kind="search_files", folder="documents", query="x").json()
    assert api.post(f"/api/tasks/{task['id']}/cancel").json()["state"] == "Cancelled"
    assert approve(api, task).status_code == 409


def test_model_tasks_still_need_provider_and_model(api):
    r = create(api, kind="plan", goal="x")
    assert r.status_code == 422


def test_paired_device_approval_is_recorded(folders, monkeypatch):
    monkeypatch.setenv("ATLAS_AUTH_REQUIRED", "true")
    monkeypatch.delenv("ATLAS_ALLOWED_HOSTS", raising=False)
    _, token = devices.register("Phone")
    with TestClient(create_app(), base_url="http://127.0.0.1:8000", client=("192.168.1.9", 5000)) as phone:
        phone.headers["Authorization"] = f"Bearer {token}"
        done = run(phone, kind="list_folder", folder="documents")
    assert any("approved by paired device 'Phone'" in e["message"] for e in done["events"])
