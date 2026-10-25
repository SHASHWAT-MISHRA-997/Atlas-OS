"""Real Windows checks. Skipped elsewhere; run by the `windows` CI job on a GitHub-hosted Windows runner."""
import os
import platform
import subprocess
import time

import pytest
from fastapi.testclient import TestClient

from app import storage
from app.main import app

pytestmark = pytest.mark.skipif(platform.system() != "Windows", reason="Windows-only checks")
client = TestClient(app)


def _notepad_pids() -> set[str]:
    out = subprocess.run(["tasklist", "/FI", "IMAGENAME eq notepad.exe", "/FO", "CSV", "/NH"],
                         capture_output=True, text=True, check=False).stdout
    return {line.split(",")[1].strip('"') for line in out.splitlines() if line.startswith('"notepad.exe"')}


def test_desktop_agent_really_launches_notepad(monkeypatch):
    monkeypatch.setenv("ATLAS_ENABLE_DESKTOP_AGENT", "true")
    before = _notepad_pids()
    r = client.post("/api/desktop/launch", json={"app_id": "notepad", "confirm": True})
    assert r.status_code == 200 and r.json()["launched"] is True
    new = set()
    for _ in range(50):
        new = _notepad_pids() - before
        if new:
            break
        time.sleep(0.2)
    assert new, "notepad.exe did not start"
    for pid in new:  # clean up only the process this test started
        subprocess.run(["taskkill", "/PID", pid, "/F"], capture_output=True, check=False)


def test_desktop_agent_stays_off_by_default(monkeypatch):
    monkeypatch.delenv("ATLAS_ENABLE_DESKTOP_AGENT", raising=False)
    assert client.post("/api/desktop/launch", json={"app_id": "notepad", "confirm": True}).status_code == 403


def test_default_data_dir_is_under_localappdata(monkeypatch):
    monkeypatch.delenv("ATLAS_DATA_DIR")
    assert str(storage.default_data_dir()).lower().startswith(os.environ["LOCALAPPDATA"].lower())


def test_file_actions_on_real_windows_paths(monkeypatch, tmp_path):
    docs = tmp_path / "Documents"
    (docs / "College").mkdir(parents=True)
    (docs / "College" / "Notes.TXT").write_text("x")
    (tmp_path / "secret").mkdir()
    monkeypatch.setenv("ATLAS_ENABLE_DESKTOP_AGENT", "true")
    monkeypatch.setenv("ATLAS_AGENT_FOLDERS", f"documents={docs}")
    from app import agent
    assert agent.list_folder("documents")["entries"][0]["name"] == "College"
    assert agent.search_files("documents", "notes")["results"] == [{"path": "College/Notes.TXT", "type": "file"}]
    for escape in ("..\\secret", "College\\..\\..\\secret", "C:\\Windows"):
        try:
            agent.list_folder("documents", escape)
        except agent.AgentError as exc:
            assert exc.code in ("outside_folder", "not_a_folder"), (escape, exc.code)
        else:
            raise AssertionError(f"{escape} was allowed")
