"""Browser control: open a website or a web search in the default browser, as approved PC actions.

``webbrowser.open`` is replaced by a recorder (a MOCK), so no real browser starts in tests.
"""
import time

import pytest
from fastapi.testclient import TestClient

from app import agent
from app.main import create_app


@pytest.fixture
def opened(monkeypatch, tmp_path):
    monkeypatch.setenv("ATLAS_ENABLE_DESKTOP_AGENT", "true")
    monkeypatch.setenv("ATLAS_AGENT_FOLDERS", f"documents={tmp_path}")
    calls = []
    monkeypatch.setattr(agent.webbrowser, "open", lambda url, new=0: calls.append(url) or True)
    return calls


@pytest.fixture
def api():
    with TestClient(create_app()) as c:
        yield c


def run(api, **body):
    task = api.post("/api/tasks", json=body).json()
    assert task["state"] == "AwaitingApproval", task
    api.post(f"/api/tasks/{task['id']}/approve", json={"approval_hash": task["approval_hash"]})
    for _ in range(100):
        done = api.get(f"/api/tasks/{task['id']}").json()
        if done["state"] in ("Succeeded", "Failed"):
            return task, done
        time.sleep(0.02)
    raise AssertionError("task did not finish")


def test_website_opens_only_after_approval(api, opened):
    task = api.post("/api/tasks", json={"kind": "open_url", "url": "https://example.com/docs?a=1"}).json()
    assert task["action"]["summary"] == "Open example.com in the browser"
    time.sleep(0.2)
    assert opened == []
    _, done = run(api, kind="open_url", url="https://example.com/docs?a=1")
    assert done["state"] == "Succeeded" and opened == ["https://example.com/docs?a=1"]


def test_lookalike_domains_are_shown_in_their_real_form(api, opened):
    task = api.post("/api/tasks", json={"kind": "open_url", "url": "https://аpple.com/"}).json()  # Cyrillic а
    assert "xn--" in task["action"]["summary"]


def test_web_search_builds_the_engine_url(api, opened):
    task, done = run(api, kind="web_search", query="DBMS normalization & 3NF", engine="google")
    assert task["action"]["summary"] == "Search Google for 'DBMS normalization & 3NF'"
    assert opened == ["https://www.google.com/search?q=DBMS+normalization+%26+3NF"]
    assert done["output"]["engine"] == "Google"


def test_search_defaults_to_duckduckgo(api, opened):
    run(api, kind="web_search", query="weather jaipur")
    assert opened[0].startswith("https://duckduckgo.com/?q=weather+jaipur")


def test_missing_browser_is_reported(api, opened, monkeypatch):
    monkeypatch.setattr(agent.webbrowser, "open", lambda url, new=0: False)
    _, done = run(api, kind="open_url", url="https://example.com")
    assert done["state"] == "Failed" and done["error"]["code"] == "no_browser"


def test_browser_actions_need_the_agent_switched_on(api, monkeypatch):
    monkeypatch.setenv("ATLAS_ENABLE_DESKTOP_AGENT", "false")
    assert api.post("/api/tasks", json={"kind": "open_url", "url": "https://example.com"}).status_code == 403
