"""Red-team cases against the desktop agent and its approval flow (research question 3, docs/RESEARCH.md).

Each case is an attempt to make ATLAS do something on the PC that the user did not approve, or to
reach files outside an approved folder. A case passes when the attempt is refused or contained.
These cases were written by the same author as the code, so they are a regression suite, not an
independent red-team evaluation.
"""
import os
import time

import pytest
from fastapi.testclient import TestClient

from app import agent, auth, devices
from app.main import create_app

LOCAL = ("127.0.0.1", 50000)
PHONE = ("192.168.1.50", 50000)


@pytest.fixture
def env(tmp_path, monkeypatch):
    docs = tmp_path / "Documents"
    (docs / "notes").mkdir(parents=True)
    (docs / "notes" / "a.txt").write_text("a")
    secret = tmp_path / "secret"
    secret.mkdir()
    (secret / "passwords.txt").write_text("hunter2")
    if hasattr(os, "symlink"):
        try:
            os.symlink(secret, docs / "escape-link", target_is_directory=True)
        except OSError:
            pass
    monkeypatch.setenv("ATLAS_AGENT_FOLDERS", f"documents={docs}")
    monkeypatch.setenv("ATLAS_ENABLE_DESKTOP_AGENT", "true")
    launched = []
    monkeypatch.setattr(agent.subprocess, "Popen", lambda cmd, **kw: launched.append(cmd))
    monkeypatch.setattr(agent.shutil, "which", lambda name: "/usr/bin/" + name)
    return {"docs": docs, "secret": secret, "launched": launched}


@pytest.fixture
def api():
    with TestClient(create_app()) as c:
        yield c


def create(api, **body):
    return api.post("/api/tasks", json=body)


def settle(api, task_id, seconds=0.3):
    time.sleep(seconds)
    return api.get(f"/api/tasks/{task_id}").json()


# --- reaching outside approved folders ------------------------------------------------

@pytest.mark.parametrize("path", ["../secret", "../../", "notes/../../secret", "escape-link"],
                         ids=["dotdot", "dotdot-root", "nested-dotdot", "symlink-dir"])
def test_paths_outside_the_folder_are_refused_before_approval(api, env, path):
    if path == "escape-link" and not (env["docs"] / "escape-link").is_symlink():
        pytest.skip("symlinks not available")
    r = create(api, kind="list_folder", folder="documents", path=path)
    assert r.status_code == 422 and r.json()["code"] == "outside_folder"


@pytest.mark.parametrize("folder", ["secret", "documents/..", "DOCUMENTS", "c:", ""], ids=["unlisted", "traversal", "case", "drive", "blank"])
def test_unapproved_folder_names_are_refused(api, env, folder):
    assert create(api, kind="list_folder", folder=folder).status_code == 422


@pytest.mark.parametrize("path", ["/etc", "/", "\\\\server\\share"], ids=["absolute", "root", "unc"])
def test_absolute_paths_are_read_inside_the_folder(api, env, path):
    task = create(api, kind="list_folder", folder="documents", path=path).json()
    api.post(f"/api/tasks/{task['id']}/approve", json={"approval_hash": task["approval_hash"]})
    done = settle(api, task["id"], 0.5)
    names = {e["name"] for e in (done.get("output") or {}).get("entries", [])}
    assert "passwords.txt" not in names and "passwd" not in names
    assert done["state"] == "Failed" or names <= {"notes", "escape-link"}


def test_nul_byte_in_path_is_refused(api, env):
    assert create(api, kind="list_folder", folder="documents", path="notes\x00/../../secret").status_code == 422


def test_encoded_traversal_is_treated_as_a_literal_name(api, env):
    r = create(api, kind="list_folder", folder="documents", path="..%2f..%2fsecret")
    task = r.json()
    api.post(f"/api/tasks/{task['id']}/approve", json={"approval_hash": task["approval_hash"]})
    done = settle(api, task["id"], 0.5)
    assert done["state"] == "Failed"  # no such folder inside Documents; nothing outside was read


def test_symlinks_inside_the_folder_are_listed_but_not_followed(api, env):
    if not (env["docs"] / "escape-link").is_symlink():
        pytest.skip("symlinks not available")
    task = create(api, kind="search_files", folder="documents", query="passwords").json()
    api.post(f"/api/tasks/{task['id']}/approve", json={"approval_hash": task["approval_hash"]})
    done = settle(api, task["id"], 0.5)
    assert done["state"] == "Succeeded" and done["output"]["results"] == []


# --- running something that is not an allowlisted typed action -------------------------

@pytest.mark.parametrize("body", [
    {"kind": "shell", "command": "whoami"},
    {"kind": "run_command", "command": "del /s C:\\"},
    {"kind": "open_app", "app_id": "powershell"},
    {"kind": "open_app", "app_id": "notepad & calc"},
    {"kind": "open_app", "app_id": "cmd.exe"},
    {"kind": "open_app"},
], ids=["shell-kind", "run-command-kind", "powershell", "chained-app", "cmd", "missing-app"])
def test_unknown_actions_and_apps_are_refused(api, env, body):
    assert create(api, **body).status_code == 422
    assert env["launched"] == []


def test_extra_fields_cannot_smuggle_a_command(api, env):
    task = create(api, kind="open_app", app_id="notepad", command="calc.exe", args=["/c", "whoami"]).json()
    api.post(f"/api/tasks/{task['id']}/approve", json={"approval_hash": task["approval_hash"]})
    settle(api, task["id"], 0.5)
    assert env["launched"] == [["notepad.exe"]] if os.name == "nt" else env["launched"][0][0] in ("gedit", "open")
    assert all("calc" not in " ".join(cmd) and "whoami" not in " ".join(cmd) for cmd in env["launched"])


# --- getting around approval --------------------------------------------------------------

def test_nothing_runs_without_approval(api, env):
    task = create(api, kind="open_app", app_id="calculator").json()
    assert settle(api, task["id"], 0.5)["state"] == "AwaitingApproval"
    assert env["launched"] == []


def test_wrong_or_reused_approval_is_refused(api, env):
    task = create(api, kind="open_app", app_id="calculator").json()
    assert api.post(f"/api/tasks/{task['id']}/approve", json={"approval_hash": "0" * 64}).status_code == 409
    other = create(api, kind="open_app", app_id="notepad").json()
    # An approval for one action cannot approve a different one.
    assert api.post(f"/api/tasks/{task['id']}/approve", json={"approval_hash": other["approval_hash"]}).status_code == 409
    assert env["launched"] == []


def test_approving_twice_runs_once(api, env):
    task = create(api, kind="open_app", app_id="calculator").json()
    assert api.post(f"/api/tasks/{task['id']}/approve", json={"approval_hash": task["approval_hash"]}).status_code == 200
    assert api.post(f"/api/tasks/{task['id']}/approve", json={"approval_hash": task["approval_hash"]}).status_code == 409
    settle(api, task["id"], 0.5)
    assert len(env["launched"]) == 1


def test_switching_the_agent_off_blocks_already_queued_approvals(api, env, monkeypatch):
    task = create(api, kind="open_app", app_id="calculator").json()
    monkeypatch.setenv("ATLAS_ENABLE_DESKTOP_AGENT", "false")
    from app.config import get_settings
    get_settings.cache_clear() if hasattr(get_settings, "cache_clear") else None
    assert api.post(f"/api/tasks/{task['id']}/approve", json={"approval_hash": task["approval_hash"]}).status_code == 403
    assert env["launched"] == []


# --- who may ask --------------------------------------------------------------------------

@pytest.fixture
def auth_on(monkeypatch):
    monkeypatch.setenv("ATLAS_AUTH_REQUIRED", "true")
    monkeypatch.delenv("ATLAS_ALLOWED_HOSTS", raising=False)
    devices._pending.clear()


def _client(addr):
    return TestClient(create_app(), base_url="http://127.0.0.1:8000", client=addr)


def test_strangers_cannot_create_or_approve_actions(env, auth_on):
    stranger = _client(PHONE)
    assert stranger.post("/api/tasks", json={"kind": "open_app", "app_id": "calculator"}).status_code == 401
    assert stranger.post("/api/desktop/launch", json={"app_id": "calculator", "confirm": True}).status_code == 401
    assert env["launched"] == []


def test_paired_phone_cannot_use_the_direct_launcher(env, auth_on):
    owner = _client(LOCAL)
    owner.get("/")
    code = owner.post("/api/devices/pairing", json={"name": "Phone"}).json()["code"]
    phone = _client(PHONE)
    phone.get(f"/?pair={code}", follow_redirects=False)
    r = phone.post("/api/desktop/launch", json={"app_id": "calculator", "confirm": True})
    assert r.status_code == 403
    assert env["launched"] == []


def test_cross_site_pages_cannot_create_actions(env, auth_on):
    owner = _client(LOCAL)
    owner.get("/")
    r = owner.post("/api/tasks", json={"kind": "open_app", "app_id": "calculator"}, headers={"origin": "https://evil.example"})
    assert r.status_code == 403
    assert env["launched"] == []


def test_a_tunnel_on_the_pc_does_not_get_owner_rights(env, auth_on):
    via_tunnel = _client(LOCAL)
    r = via_tunnel.get("/", headers={"x-forwarded-for": "203.0.113.9"})
    assert "set-cookie" not in r.headers
    assert via_tunnel.post("/api/tasks", json={"kind": "open_app", "app_id": "calculator"},
                           headers={"x-forwarded-for": "203.0.113.9"}).status_code == 401
    assert auth.get_token() not in str(r.headers)


# --- writing, trash and documents (v0.8) --------------------------------------------------

@pytest.mark.parametrize("body", [
    {"name": "../evil"}, {"name": "..\\evil"}, {"name": "notes/evil"}, {"name": ".bashrc"},
    {"name": "CON"}, {"name": "nul.txt"}, {"name": "ok", "path": "../secret"}, {"name": "ok", "path": "escape-link"},
], ids=["dotdot-name", "backslash-name", "slash-name", "dotfile", "windows-device", "windows-device-ext",
        "dotdot-folder", "symlink-folder"])
def test_new_files_cannot_be_written_outside_or_to_devices(api, env, body):
    if body.get("path") == "escape-link" and not (env["docs"] / "escape-link").is_symlink():
        pytest.skip("symlinks not available")
    r = create(api, kind="create_note", folder="documents", text="x", **body)
    assert r.status_code == 422
    assert sorted(p.name for p in env["secret"].iterdir()) == ["passwords.txt"]


def test_existing_files_are_never_overwritten(api, env):
    r = create(api, kind="create_note", folder="documents", path="notes", name="a.txt", text="replaced")
    assert r.status_code == 409
    assert (env["docs"] / "notes" / "a.txt").read_text() == "a"


@pytest.mark.parametrize("path", ["../secret/passwords.txt", "escape-link/passwords.txt", "notes"],
                         ids=["dotdot", "through-symlink", "folder"])
def test_trash_cannot_take_files_from_outside_or_whole_folders(api, env, path):
    if path.startswith("escape-link") and not (env["docs"] / "escape-link").is_symlink():
        pytest.skip("symlinks not available")
    r = create(api, kind="move_to_trash", folder="documents", path=path)
    if r.status_code == 202:
        api.post(f"/api/tasks/{r.json()['id']}/approve", json={"approval_hash": r.json()["approval_hash"]})
        assert settle(api, r.json()["id"], 0.5)["state"] == "Failed"
    else:
        assert r.status_code == 422
    assert (env["secret"] / "passwords.txt").read_text() == "hunter2"
    assert (env["docs"] / "notes" / "a.txt").exists()


def test_restore_never_overwrites_a_new_file(api, env, tmp_path, monkeypatch):
    monkeypatch.setenv("ATLAS_DATA_DIR", str(tmp_path / "data"))
    task = create(api, kind="move_to_trash", folder="documents", path="notes/a.txt").json()
    api.post(f"/api/tasks/{task['id']}/approve", json={"approval_hash": task["approval_hash"]})
    trash_id = settle(api, task["id"], 0.5)["output"]["trash_id"]
    (env["docs"] / "notes" / "a.txt").write_text("newer")
    task = create(api, kind="restore_from_trash", trash_id=trash_id).json()
    api.post(f"/api/tasks/{task['id']}/approve", json={"approval_hash": task["approval_hash"]})
    assert settle(api, task["id"], 0.5)["state"] == "Failed"
    assert (env["docs"] / "notes" / "a.txt").read_text() == "newer"


def test_indexing_does_not_follow_links_out_of_the_folder(api, env, tmp_path, monkeypatch):
    if not (env["docs"] / "escape-link").is_symlink():
        pytest.skip("symlinks not available")
    monkeypatch.setenv("ATLAS_DATA_DIR", str(tmp_path / "data"))
    task = create(api, kind="index_documents", folder="documents").json()
    api.post(f"/api/tasks/{task['id']}/approve", json={"approval_hash": task["approval_hash"]})
    assert settle(api, task["id"], 0.8)["state"] == "Succeeded"
    assert api.get("/api/docs/search", params={"q": "hunter2"}).json()["results"] == []


@pytest.mark.parametrize("q", ['"', "NEAR(a b)", "a OR", "*", "col:val", "') DROP TABLE doc_chunks; --"])
def test_search_syntax_cannot_break_the_query(api, env, q):
    assert api.get("/api/docs/search", params={"q": q}).status_code == 200


# --- browser control (v0.9) ------------------------------------------------------------------

@pytest.mark.parametrize("url", [
    "file:///C:/Windows/System32/config/SAM", "javascript:alert(1)", "data:text/html,<script>x</script>",
    "ms-settings:privacy", "\\\\server\\share", "https://user:pass@example.com/", "http://localhost:8000/api/memory",
    "http://127.0.0.1:8000/", "http://[::1]/", "http://192.168.1.1/admin", "http://10.0.0.5/", "http://169.254.169.254/latest/",
    "http://printer.local/", "https://example.com/ calc.exe", "https://example.com/\nnext", "http://0.0.0.0/",
], ids=["file", "javascript", "data", "ms-settings", "unc", "credentials", "localhost-api", "loopback", "ipv6-loopback",
        "router", "private-10", "cloud-metadata", "mdns", "space", "newline", "zero"])
def test_only_public_web_pages_can_be_opened(api, env, url, monkeypatch):
    opened = []
    monkeypatch.setattr(agent.webbrowser, "open", lambda u, new=0: opened.append(u) or True)
    assert create(api, kind="open_url", url=url).status_code == 422
    assert opened == [] and env["launched"] == []


def test_search_words_cannot_change_the_search_address(api, env, monkeypatch):
    opened = []
    monkeypatch.setattr(agent.webbrowser, "open", lambda u, new=0: opened.append(u) or True)
    task = create(api, kind="web_search", query="x&q=evil#https://evil.example/", engine="bing").json()
    api.post(f"/api/tasks/{task['id']}/approve", json={"approval_hash": task["approval_hash"]})
    settle(api, task["id"], 0.5)
    assert opened == ["https://www.bing.com/search?q=x%26q%3Devil%23https%3A%2F%2Fevil.example%2F"]
