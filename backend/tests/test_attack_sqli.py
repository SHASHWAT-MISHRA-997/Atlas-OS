"""SQL injection sweep: classic payloads go into every text field, query parameter and id in
the storage API. Nothing may crash (500), leak rows, or change the database. Real SQLite, no mocks."""
import sqlite3
from urllib.parse import quote

import pytest
from fastapi.testclient import TestClient

from app import storage
from app.main import app

client = TestClient(app)

PAYLOADS = [
    "' OR '1'='1",
    "'; DROP TABLE memories; --",
    "\" OR 1=1 --",
    "1; DELETE FROM chat_messages",
    "x' UNION SELECT id, text, text, text FROM memories --",
    "') OR ('a'='a",
    "%' OR 1=1 --",
    "*",
    "NEAR(a b)",
    "\x00",
    "' AND randomblob(1000000000) --",
]


def tables():
    with sqlite3.connect(storage.db_path()) as conn:
        return {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type = 'table'")}


def counts():
    with sqlite3.connect(storage.db_path()) as conn:
        return {t: conn.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0] for t in ("memories", "chat_messages")}  # noqa: S608 - fixed names


@pytest.fixture
def seeded():
    client.post("/api/memory", json={"text": "secret memory alpha"})
    client.post("/api/chat/history", json={"role": "user", "content": "private chat"})
    client.post("/api/chat/history", params={"conversation": "other"}, json={"role": "user", "content": "other chat"})
    return tables(), counts()


@pytest.mark.parametrize("payload", PAYLOADS)
def test_injection_payloads_change_nothing_and_leak_nothing(seeded, payload):
    before_tables, before_counts = seeded
    q = quote(payload, safe="")
    responses = [
        client.get(f"/api/memory?q={q}"),
        client.get(f"/api/chat/history?conversation={q}"),
        client.post(f"/api/chat/history?conversation={q}", json={"role": "user", "content": "x"}),
        client.post(f"/api/chat/history/clear?conversation={q}", json={"confirm": True}),
        client.patch(f"/api/memory/{q}", json={"text": "changed"}),
        client.delete(f"/api/memory/{q}"),
        client.delete(f"/api/chat/history/{q}"),
        client.get(f"/api/tasks/{q}"),
        client.post(f"/api/tasks/{q}/cancel"),
        client.get(f"/api/docs/search?q={q}"),
    ]
    for r in responses:
        assert r.status_code < 500, (r.request.method, r.request.url, r.status_code, r.text)
    # Search with a payload finds only real matches, never every row.
    found = client.get(f"/api/memory?q={q}").json()["memories"]
    assert all(payload.lower() in m["text"].lower() for m in found)
    assert tables() == before_tables
    assert counts() == before_counts


def test_payloads_are_stored_as_plain_text(seeded):
    for payload in PAYLOADS[:6]:
        r = client.post("/api/memory", json={"text": "note " + payload})
        assert r.status_code == 201
    texts = {m["text"] for m in client.get("/api/memory").json()["memories"]}
    assert {"note " + p for p in PAYLOADS[:6]} <= texts
    assert "memories" in tables()
