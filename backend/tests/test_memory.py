"""Server-side memory and chat history (real SQLite in a per-test temp directory, no mocks)."""
import sqlite3

from fastapi.testclient import TestClient

from app import storage
from app.main import app, create_app

client = TestClient(app)


def add(text):
    r = client.post("/api/memory", json={"text": text})
    assert r.status_code == 201, r.text
    return r.json()


def test_memory_crud_round_trip():
    item = add("Prefer answers in Hinglish")
    listed = client.get("/api/memory").json()
    assert listed["count"] == 1 and listed["enabled"] is True
    assert listed["memories"][0]["text"] == "Prefer answers in Hinglish"

    r = client.patch(f"/api/memory/{item['id']}", json={"text": "Prefer answers in Hindi"})
    assert r.status_code == 200 and r.json()["updated_at"]
    assert client.get("/api/memory").json()["memories"][0]["text"] == "Prefer answers in Hindi"

    assert client.delete(f"/api/memory/{item['id']}").status_code == 204
    assert client.get("/api/memory").json()["count"] == 0
    assert client.delete(f"/api/memory/{item['id']}").status_code == 404
    assert client.patch(f"/api/memory/{item['id']}", json={"text": "x"}).status_code == 404


def test_memory_survives_an_app_restart():
    add("ATLAS should prefer free local models")
    restarted = TestClient(create_app())
    assert restarted.get("/api/memory").json()["memories"][0]["text"] == "ATLAS should prefer free local models"


def test_memory_validation():
    assert client.post("/api/memory", json={"text": "   "}).status_code == 422
    assert client.post("/api/memory", json={"text": "x" * 1001}).status_code == 422


def test_search_uses_the_full_text_index_and_reflects_edits_and_deletes():
    a = add("Project deadline is Friday")
    add("Favourite editor is VS Code")
    assert [m["text"] for m in client.get("/api/memory", params={"q": "deadl"}).json()["memories"]] == ["Project deadline is Friday"]
    client.patch(f"/api/memory/{a['id']}", json={"text": "Project due Monday"})
    assert client.get("/api/memory", params={"q": "deadline"}).json()["memories"] == []
    assert len(client.get("/api/memory", params={"q": "monday"}).json()["memories"]) == 1
    client.delete(f"/api/memory/{a['id']}")
    assert client.get("/api/memory", params={"q": "monday"}).json()["memories"] == []


def test_search_tolerates_fts_syntax_in_user_input():
    add("plain memory")
    for q in ['"', "AND OR NOT", "x* NEAR(", "'; DROP TABLE memories; --", "***"]:
        r = client.get("/api/memory", params={"q": q})
        assert r.status_code == 200, q
    assert client.get("/api/memory").json()["count"] == 1


def test_deleted_text_is_removed_from_the_database_file():
    secret = "zebra-unique-marker-4417"
    item = add(f"My locker code note {secret}")
    client.delete(f"/api/memory/{item['id']}")
    conn = sqlite3.connect(storage.db_path())
    conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
    conn.close()
    raw = storage.db_path().read_bytes()
    wal = storage.db_path().with_name("atlas.db-wal")
    if wal.exists():
        raw += wal.read_bytes()
    assert secret.encode() not in raw


def test_clear_all_requires_confirmation():
    add("one")
    add("two")
    r = client.post("/api/memory/clear", json={})
    assert r.status_code == 400 and r.json()["code"] == "confirm_required"
    assert client.post("/api/memory/clear", json={"confirm": True}).json() == {"deleted": 2}
    assert client.get("/api/memory").json()["count"] == 0
    assert client.get("/api/memory", params={"q": "one"}).json()["memories"] == []


def test_memory_can_be_disabled():
    assert client.put("/api/memory/settings", json={"enabled": False}).json() == {"enabled": False}
    assert client.get("/api/memory").json()["enabled"] is False
    assert TestClient(create_app()).get("/api/memory").json()["enabled"] is False


def test_import_merges_skips_duplicates_and_accepts_browser_format():
    add("already here")
    r = client.post("/api/memory/import", json={"memories": [
        {"text": "already here"},
        {"text": "from browser", "createdAt": "2026-10-01T10:00:00.000Z"},
        {"text": "from browser"},
    ]})
    assert r.json() == {"imported": 1, "skipped": 2}
    imported = [m for m in client.get("/api/memory").json()["memories"] if m["text"] == "from browser"][0]
    assert imported["created_at"].startswith("2026-10-01T10:00:00")


def test_import_is_all_or_nothing_on_invalid_items():
    r = client.post("/api/memory/import", json={"memories": [{"text": "good"}, {"text": " "}]})
    assert r.status_code == 422
    assert client.get("/api/memory").json()["count"] == 0


def test_memory_limit_is_enforced(monkeypatch):
    monkeypatch.setattr(storage, "MAX_MEMORIES", 2)
    add("a")
    add("b")
    r = client.post("/api/memory", json={"text": "c"})
    assert r.status_code == 409 and r.json()["code"] == "memory_limit"
    assert client.post("/api/memory/import", json={"memories": [{"text": "d"}]}).status_code == 409


def test_chat_history_append_list_prune_and_clear(monkeypatch):
    monkeypatch.setattr(storage, "MAX_CHAT_MESSAGES", 3)
    for i in range(5):
        r = client.post("/api/chat/history", json={"role": "user" if i % 2 == 0 else "assistant", "content": f"m{i}"})
        assert r.status_code == 201
    msgs = client.get("/api/chat/history").json()["messages"]
    assert [m["content"] for m in msgs] == ["m2", "m3", "m4"]
    client.post("/api/chat/history", params={"conversation": "other"}, json={"role": "user", "content": "x"})
    assert client.post("/api/chat/history/clear", json={}).status_code == 400
    assert client.post("/api/chat/history/clear", json={"confirm": True}).json() == {"deleted": 3}
    assert len(client.get("/api/chat/history", params={"conversation": "other"}).json()["messages"]) == 1


def test_chat_message_delete_one_or_from_an_edited_message_onward():
    ids = [client.post("/api/chat/history", json={"role": "user" if i % 2 == 0 else "assistant", "content": f"m{i}"}).json()["id"]
           for i in range(4)]
    other = client.post("/api/chat/history", params={"conversation": "other"}, json={"role": "user", "content": "x"}).json()["id"]
    assert client.delete(f"/api/chat/history/{ids[0]}").json() == {"deleted": 1}
    # Editing m2 removes it and the reply after it, but not other conversations.
    assert client.delete(f"/api/chat/history/{ids[2]}", params={"following": "true"}).json() == {"deleted": 2}
    assert [m["content"] for m in client.get("/api/chat/history").json()["messages"]] == ["m1"]
    assert client.delete(f"/api/chat/history/{ids[0]}").status_code == 404
    assert client.delete(f"/api/chat/history/{other}").status_code == 404  # wrong conversation
    assert len(client.get("/api/chat/history", params={"conversation": "other"}).json()["messages"]) == 1


def test_chat_history_rejects_bad_input():
    assert client.post("/api/chat/history", json={"role": "system", "content": "x"}).status_code == 422
    assert client.post("/api/chat/history", json={"role": "user", "content": ""}).status_code == 422
    assert client.get("/api/chat/history", params={"conversation": "../etc"}).status_code == 422


def test_export_contains_memories_chat_and_settings():
    add("export me")
    client.post("/api/chat/history", json={"role": "user", "content": "hello"})
    data = client.get("/api/storage/export").json()
    assert data["format"] == "atlas-os-export" and data["version"] == 1
    assert data["memories"][0]["text"] == "export me"
    assert data["chat"]["default"][0]["content"] == "hello"
    assert data["settings"] == {"memory_enabled": True, "retention": {"chat_days": None, "memory_days": None}}


def test_backup_and_restore_round_trip():
    add("keep this")
    r = client.post("/api/storage/backup")
    assert r.status_code == 200 and r.json()["bytes"] > 0
    backup_file = storage.data_dir() / "backups" / r.json()["file"]
    client.post("/api/memory/clear", json={"confirm": True})
    add("added after backup")
    storage.restore(backup_file)
    texts = [m["text"] for m in client.get("/api/memory").json()["memories"]]
    assert texts == ["keep this"]
    assert client.get("/api/memory", params={"q": "keep"}).json()["memories"]  # index restored too


def test_restore_rejects_files_that_are_not_atlas_databases(tmp_path):
    other = tmp_path / "other.db"
    conn = sqlite3.connect(other)
    conn.execute("CREATE TABLE something(x)")
    conn.commit()
    conn.close()
    add("still here")
    try:
        storage.restore(other)
    except storage.StorageError as exc:
        assert exc.code == "not_atlas_backup"
    else:
        raise AssertionError("restore accepted a foreign database")
    assert client.get("/api/memory").json()["count"] == 1


def test_schema_is_versioned():
    assert storage.schema_version() == len(storage.MIGRATIONS)


def test_storage_is_off_in_production_unless_enabled(monkeypatch):
    monkeypatch.setenv("ATLAS_ENV", "production")
    r = client.get("/api/memory")
    assert r.status_code == 503 and r.json()["code"] == "storage_disabled"
    assert client.get("/api/system/status").json()["memory_storage"] == "browser-local"
    monkeypatch.setenv("ATLAS_SERVER_STORAGE", "true")
    assert client.get("/api/memory").status_code == 200


def test_data_dir_defaults_to_user_profile(monkeypatch):
    monkeypatch.delenv("ATLAS_DATA_DIR")
    path = storage.default_data_dir()
    assert path.name in {"AtlasOS", "atlas-os"}


def test_cli_backup_and_path(capsys):
    add("cli")
    assert storage._main(["path"]) == 0
    assert capsys.readouterr().out.strip().endswith("atlas.db")
    assert storage._main(["backup"]) == 0
    assert capsys.readouterr().out.strip().endswith(".db")
