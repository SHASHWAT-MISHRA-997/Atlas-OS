"""Retention rules: opt-in auto-deletion of old chat messages and memories."""
from datetime import UTC, datetime, timedelta

import pytest
from fastapi.testclient import TestClient

from app import storage
from app.main import app

client = TestClient(app)


@pytest.fixture(autouse=True)
def clean():
    client.put("/api/storage/retention", json={})
    client.post("/api/memory/clear", json={"confirm": True})
    client.post("/api/chat/history/clear", json={"confirm": True})
    yield
    client.put("/api/storage/retention", json={})


def days_ago(n):
    return (datetime.now(UTC) - timedelta(days=n)).isoformat(timespec="seconds")


def old_chat(content, age_days):
    with storage.connection() as conn, conn:
        conn.execute("INSERT INTO chat_messages(conversation_id, role, content, created_at) VALUES ('default', 'user', ?, ?)",
                     (content, days_ago(age_days)))


def test_retention_is_off_by_default_and_keeps_everything():
    assert client.get("/api/storage/retention").json() == {"chat_days": None, "memory_days": None}
    client.post("/api/memory/import", json={"memories": [{"text": "ancient fact", "created_at": days_ago(4000)}]})
    old_chat("ancient message", 4000)
    assert [m["text"] for m in client.get("/api/memory").json()["memories"]] == ["ancient fact"]
    assert [m["content"] for m in client.get("/api/chat/history").json()["messages"]] == ["ancient message"]


def test_setting_retention_deletes_old_items_now_and_keeps_recent_ones():
    client.post("/api/memory/import", json={"memories": [
        {"text": "old fact", "created_at": days_ago(40)}, {"text": "new fact", "created_at": days_ago(2)}]})
    old_chat("old message", 10)
    old_chat("new message", 1)
    r = client.put("/api/storage/retention", json={"chat_days": 7, "memory_days": 30})
    assert r.status_code == 200
    assert r.json() == {"chat_days": 7, "memory_days": 30, "deleted": {"chat": 1, "memories": 1}}
    assert [m["text"] for m in client.get("/api/memory").json()["memories"]] == ["new fact"]
    assert [m["content"] for m in client.get("/api/chat/history").json()["messages"]] == ["new message"]


def test_rules_keep_applying_when_data_is_read():
    client.put("/api/storage/retention", json={"chat_days": 7})
    old_chat("aged out later", 8)  # e.g. a message that crossed the line since the last read
    assert client.get("/api/chat/history").json()["messages"] == []


def test_recently_edited_memory_counts_as_recent():
    client.post("/api/memory/import", json={"memories": [{"text": "old but edited", "created_at": days_ago(90)}]})
    memory_id = client.get("/api/memory").json()["memories"][0]["id"]
    client.patch(f"/api/memory/{memory_id}", json={"text": "old but edited today"})
    client.put("/api/storage/retention", json={"memory_days": 30})
    assert [m["text"] for m in client.get("/api/memory").json()["memories"]] == ["old but edited today"]


def test_retention_is_validated_and_can_be_switched_off():
    assert client.put("/api/storage/retention", json={"chat_days": 0}).status_code == 422
    assert client.put("/api/storage/retention", json={"memory_days": 99999}).status_code == 422
    client.put("/api/storage/retention", json={"chat_days": 30})
    assert client.put("/api/storage/retention", json={"chat_days": None}).json()["chat_days"] is None


def test_export_includes_the_retention_rules():
    client.put("/api/storage/retention", json={"chat_days": 30})
    assert client.get("/api/storage/export").json()["settings"]["retention"] == {"chat_days": 30, "memory_days": None}
