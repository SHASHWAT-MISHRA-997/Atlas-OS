"""Local SQLite storage for user-controlled memory and chat history.

Single-user and local-first: the database lives in the user's data directory on
the machine running the backend. There is no per-user separation, so server
storage is off when ATLAS_ENV=production unless explicitly enabled (see
docs/THREAT_MODEL.md T15).

CLI (from backend/):  python -m app.storage backup | restore <file> | path
"""
from __future__ import annotations

import json
import os
import re
import sqlite3
import sys
import uuid
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime, timedelta
from pathlib import Path

from .config import get_settings

MAX_MEMORY_CHARS = 1000
MAX_MEMORIES = 1000
MAX_CHAT_MESSAGES = 500  # per conversation; older messages are pruned
MAX_CHAT_CHARS = 20000

MIGRATIONS: list[str] = [
    # 1: memories with full-text index kept in sync by triggers, chat history, settings
    """
    CREATE TABLE memories (
        id TEXT PRIMARY KEY,
        text TEXT NOT NULL CHECK (length(text) BETWEEN 1 AND 1000),
        created_at TEXT NOT NULL,
        updated_at TEXT
    );
    CREATE INDEX memories_created ON memories(created_at);
    CREATE VIRTUAL TABLE memories_fts USING fts5(text, content='memories', content_rowid='rowid');
    CREATE TRIGGER memories_ai AFTER INSERT ON memories BEGIN
        INSERT INTO memories_fts(rowid, text) VALUES (new.rowid, new.text);
    END;
    CREATE TRIGGER memories_ad AFTER DELETE ON memories BEGIN
        INSERT INTO memories_fts(memories_fts, rowid, text) VALUES ('delete', old.rowid, old.text);
    END;
    CREATE TRIGGER memories_au AFTER UPDATE ON memories BEGIN
        INSERT INTO memories_fts(memories_fts, rowid, text) VALUES ('delete', old.rowid, old.text);
        INSERT INTO memories_fts(rowid, text) VALUES (new.rowid, new.text);
    END;
    CREATE TABLE chat_messages (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        conversation_id TEXT NOT NULL,
        role TEXT NOT NULL CHECK (role IN ('user', 'assistant')),
        content TEXT NOT NULL CHECK (length(content) BETWEEN 1 AND 20000),
        meta TEXT,
        created_at TEXT NOT NULL
    );
    CREATE INDEX chat_conversation ON chat_messages(conversation_id, id);
    CREATE TABLE settings (key TEXT PRIMARY KEY, value TEXT NOT NULL);
    """,
    # 2: background tasks and their audit events. API keys are never stored here.
    """
    CREATE TABLE tasks (
        id TEXT PRIMARY KEY,
        kind TEXT NOT NULL,
        state TEXT NOT NULL CHECK (state IN ('Queued','Planning','AwaitingApproval','Running','Paused','Succeeded','Failed','Cancelled')),
        priority INTEGER NOT NULL DEFAULT 0,
        params TEXT NOT NULL,
        approval_hash TEXT NOT NULL,
        idempotency_key TEXT UNIQUE,
        resource TEXT,
        steps_done INTEGER NOT NULL DEFAULT 0,
        steps_total INTEGER,
        progress_note TEXT,
        output TEXT,
        error_code TEXT,
        error TEXT,
        created_at TEXT NOT NULL,
        started_at TEXT,
        finished_at TEXT
    );
    CREATE INDEX tasks_created ON tasks(created_at);
    CREATE TABLE task_events (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        task_id TEXT NOT NULL REFERENCES tasks(id) ON DELETE CASCADE,
        ts TEXT NOT NULL,
        type TEXT NOT NULL,
        message TEXT NOT NULL
    );
    CREATE INDEX task_events_task ON task_events(task_id, id);
    """,
    # 3: retention rules delete chat by age
    """
    CREATE INDEX chat_created ON chat_messages(created_at);
    """,
    # 4: document search index (app/docsearch.py): text of files in approved folders
    """
    CREATE TABLE doc_files (
        folder TEXT NOT NULL,
        path TEXT NOT NULL,
        size INTEGER NOT NULL,
        mtime REAL NOT NULL,
        chunks INTEGER NOT NULL,
        error TEXT,
        indexed_at TEXT NOT NULL,
        PRIMARY KEY (folder, path)
    );
    CREATE TABLE doc_chunks (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        folder TEXT NOT NULL,
        path TEXT NOT NULL,
        chunk INTEGER NOT NULL,
        text TEXT NOT NULL
    );
    CREATE INDEX doc_chunks_file ON doc_chunks(folder, path);
    CREATE VIRTUAL TABLE doc_chunks_fts USING fts5(text, content='doc_chunks', content_rowid='id',
                                                  tokenize='unicode61 remove_diacritics 2');
    CREATE TRIGGER doc_chunks_ai AFTER INSERT ON doc_chunks BEGIN
        INSERT INTO doc_chunks_fts(rowid, text) VALUES (new.id, new.text);
    END;
    CREATE TRIGGER doc_chunks_ad AFTER DELETE ON doc_chunks BEGIN
        INSERT INTO doc_chunks_fts(doc_chunks_fts, rowid, text) VALUES ('delete', old.id, old.text);
    END;
    """,
    # 5: automations (app/automations.py): tasks created on a schedule. API keys are never stored.
    """
    CREATE TABLE automations (
        id TEXT PRIMARY KEY,
        name TEXT NOT NULL,
        task TEXT NOT NULL,
        schedule TEXT NOT NULL,
        enabled INTEGER NOT NULL DEFAULT 1,
        next_run TEXT,
        last_run TEXT,
        last_task_id TEXT,
        last_error TEXT,
        created_at TEXT NOT NULL
    );
    """,
]


class StorageError(Exception):
    def __init__(self, status_code: int, code: str, message: str):
        super().__init__(message)
        self.status_code = status_code
        self.code = code
        self.message = message


def default_data_dir() -> Path:
    if os.name == "nt":
        base = os.getenv("LOCALAPPDATA") or str(Path.home() / "AppData" / "Local")
        return Path(base) / "AtlasOS"
    base = os.getenv("XDG_DATA_HOME") or str(Path.home() / ".local" / "share")
    return Path(base) / "atlas-os"


def data_dir() -> Path:
    raw = os.getenv("ATLAS_DATA_DIR")
    return Path(raw).expanduser().resolve() if raw else default_data_dir()


def db_path() -> Path:
    return data_dir() / "atlas.db"


def server_storage_enabled() -> bool:
    raw = os.getenv("ATLAS_SERVER_STORAGE")
    if raw is not None and raw.strip():
        return raw.strip().lower() in {"1", "true", "yes", "on"}
    return not get_settings().is_production


def _now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


def _connect(path: Path | None = None) -> sqlite3.Connection:
    path = path or db_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    if os.name != "nt":
        try:
            os.chmod(path.parent, 0o700)
        except OSError:
            pass
    conn = sqlite3.connect(path, timeout=5)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA journal_mode = WAL")
    # Overwrite deleted content in the file instead of leaving it in free pages.
    conn.execute("PRAGMA secure_delete = ON")
    _migrate(conn)
    return conn


def _migrate(conn: sqlite3.Connection) -> None:
    version = conn.execute("PRAGMA user_version").fetchone()[0]
    for index, script in enumerate(MIGRATIONS[version:], start=version + 1):
        conn.executescript("BEGIN;" + script + f"PRAGMA user_version = {index};COMMIT;")


@contextmanager
def connection() -> Iterator[sqlite3.Connection]:
    if not server_storage_enabled():
        raise StorageError(503, "storage_disabled",
                           "Server storage is disabled (ATLAS_SERVER_STORAGE=false or production mode).")
    conn = _connect()
    try:
        yield conn
    finally:
        conn.close()


def schema_version() -> int:
    with connection() as conn:
        return conn.execute("PRAGMA user_version").fetchone()[0]


# --- settings ----------------------------------------------------------------

def get_memory_enabled(conn: sqlite3.Connection) -> bool:
    row = conn.execute("SELECT value FROM settings WHERE key = 'memory_enabled'").fetchone()
    return row is None or row["value"] == "true"


def set_memory_enabled(conn: sqlite3.Connection, enabled: bool) -> None:
    with conn:
        conn.execute("INSERT INTO settings(key, value) VALUES ('memory_enabled', ?) "
                     "ON CONFLICT(key) DO UPDATE SET value = excluded.value", ("true" if enabled else "false",))


RETENTION_KEYS = {"chat_days": "chat_retention_days", "memory_days": "memory_retention_days"}
MAX_RETENTION_DAYS = 3650


def get_retention(conn: sqlite3.Connection) -> dict:
    """Days to keep chat and memories; None means keep until deleted by hand (the default)."""
    out = {}
    for name, key in RETENTION_KEYS.items():
        row = conn.execute("SELECT value FROM settings WHERE key = ?", (key,)).fetchone()
        out[name] = int(row["value"]) if row and row["value"].isdigit() else None
    return out


def set_retention(conn: sqlite3.Connection, chat_days: int | None, memory_days: int | None) -> dict:
    with conn:
        for key, days in ((RETENTION_KEYS["chat_days"], chat_days), (RETENTION_KEYS["memory_days"], memory_days)):
            if days is None:
                conn.execute("DELETE FROM settings WHERE key = ?", (key,))
            else:
                if not 1 <= days <= MAX_RETENTION_DAYS:
                    raise StorageError(422, "bad_retention", f"Retention must be 1-{MAX_RETENTION_DAYS} days, or off.")
                conn.execute("INSERT INTO settings(key, value) VALUES (?, ?) "
                             "ON CONFLICT(key) DO UPDATE SET value = excluded.value", (key, str(days)))
    return apply_retention(conn)


def apply_retention(conn: sqlite3.Connection, now: datetime | None = None) -> dict:
    """Delete chat messages and memories older than their retention period. Returns what was deleted."""
    rules = get_retention(conn)
    now = now or datetime.now(UTC)
    deleted = {"chat": 0, "memories": 0}
    with conn:
        if rules["chat_days"]:
            cutoff = (now - timedelta(days=rules["chat_days"])).isoformat(timespec="seconds")
            deleted["chat"] = conn.execute("DELETE FROM chat_messages WHERE created_at < ?", (cutoff,)).rowcount
        if rules["memory_days"]:
            # A memory edited recently counts as recent.
            cutoff = (now - timedelta(days=rules["memory_days"])).isoformat(timespec="seconds")
            deleted["memories"] = conn.execute(
                "DELETE FROM memories WHERE COALESCE(updated_at, created_at) < ?", (cutoff,)).rowcount
    return {**rules, "deleted": deleted}


# --- memories ----------------------------------------------------------------

def _clean_text(text: str) -> str:
    text = (text or "").strip()
    if not text:
        raise StorageError(422, "blank_memory", "Memory text must not be blank.")
    if len(text) > MAX_MEMORY_CHARS:
        raise StorageError(422, "memory_too_long", f"Memory text must be at most {MAX_MEMORY_CHARS} characters.")
    return text


def _memory(row: sqlite3.Row) -> dict:
    return {"id": row["id"], "text": row["text"], "created_at": row["created_at"], "updated_at": row["updated_at"]}


def _fts_query(q: str) -> str | None:
    """Turn free text into a safe FTS5 query: every word must match as a prefix."""
    words = re.findall(r"\w+", q, flags=re.UNICODE)[:12]
    return " ".join(f'"{w}"*' for w in words) if words else None


def list_memories(conn: sqlite3.Connection, q: str | None = None, limit: int = 200) -> list[dict]:
    limit = max(1, min(limit, MAX_MEMORIES))
    query = _fts_query(q) if q else None
    if q and not query:
        return []
    if query:
        rows = conn.execute(
            "SELECT m.* FROM memories_fts f JOIN memories m ON m.rowid = f.rowid "
            "WHERE memories_fts MATCH ? ORDER BY rank LIMIT ?", (query, limit)).fetchall()
    else:
        rows = conn.execute("SELECT * FROM memories ORDER BY created_at DESC, rowid DESC LIMIT ?", (limit,)).fetchall()
    return [_memory(r) for r in rows]


def count_memories(conn: sqlite3.Connection) -> int:
    return conn.execute("SELECT count(*) FROM memories").fetchone()[0]


def add_memory(conn: sqlite3.Connection, text: str, created_at: str | None = None) -> dict:
    text = _clean_text(text)
    if count_memories(conn) >= MAX_MEMORIES:
        raise StorageError(409, "memory_limit", f"Memory limit reached ({MAX_MEMORIES}). Delete old memories first.")
    item = {"id": str(uuid.uuid4()), "text": text, "created_at": _valid_time(created_at) or _now(), "updated_at": None}
    with conn:
        conn.execute("INSERT INTO memories(id, text, created_at, updated_at) VALUES (:id, :text, :created_at, :updated_at)", item)
    return item


def update_memory(conn: sqlite3.Connection, memory_id: str, text: str) -> dict:
    text = _clean_text(text)
    with conn:
        cur = conn.execute("UPDATE memories SET text = ?, updated_at = ? WHERE id = ?", (text, _now(), memory_id))
    if cur.rowcount == 0:
        raise StorageError(404, "not_found", "Memory not found.")
    return _memory(conn.execute("SELECT * FROM memories WHERE id = ?", (memory_id,)).fetchone())


def delete_memory(conn: sqlite3.Connection, memory_id: str) -> None:
    with conn:
        cur = conn.execute("DELETE FROM memories WHERE id = ?", (memory_id,))
    if cur.rowcount == 0:
        raise StorageError(404, "not_found", "Memory not found.")


def delete_all_memories(conn: sqlite3.Connection) -> int:
    with conn:
        n = conn.execute("DELETE FROM memories").rowcount
        conn.execute("INSERT INTO memories_fts(memories_fts) VALUES ('rebuild')")
    return n


def import_memories(conn: sqlite3.Connection, items: list[dict]) -> dict:
    """Merge memories; skips exact duplicates. All-or-nothing on validation errors."""
    existing = {r["text"] for r in conn.execute("SELECT text FROM memories")}
    cleaned = []
    for item in items:
        text = _clean_text(str(item.get("text", "")))
        if text in existing:
            continue
        existing.add(text)
        cleaned.append((text, _valid_time(item.get("created_at") or item.get("createdAt"))))
    if count_memories(conn) + len(cleaned) > MAX_MEMORIES:
        raise StorageError(409, "memory_limit", f"Import would exceed the {MAX_MEMORIES}-memory limit.")
    with conn:
        for text, created in cleaned:
            conn.execute("INSERT INTO memories(id, text, created_at) VALUES (?, ?, ?)", (str(uuid.uuid4()), text, created or _now()))
    return {"imported": len(cleaned), "skipped": len(items) - len(cleaned)}


def _valid_time(value) -> str | None:
    if not isinstance(value, str):
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC).isoformat(timespec="seconds")


# --- chat history ------------------------------------------------------------

def list_chat(conn: sqlite3.Connection, conversation_id: str, limit: int = 40) -> list[dict]:
    rows = conn.execute(
        "SELECT * FROM (SELECT * FROM chat_messages WHERE conversation_id = ? ORDER BY id DESC LIMIT ?) ORDER BY id",
        (conversation_id, max(1, min(limit, MAX_CHAT_MESSAGES)))).fetchall()
    return [{"id": r["id"], "role": r["role"], "content": r["content"], "meta": r["meta"], "created_at": r["created_at"]} for r in rows]


def append_chat(conn: sqlite3.Connection, conversation_id: str, role: str, content: str, meta: str | None) -> dict:
    if role not in ("user", "assistant"):
        raise StorageError(422, "bad_role", "Role must be 'user' or 'assistant'.")
    if not content.strip() or len(content) > MAX_CHAT_CHARS:
        raise StorageError(422, "bad_content", f"Message must be 1-{MAX_CHAT_CHARS} characters.")
    created = _now()
    with conn:
        cur = conn.execute("INSERT INTO chat_messages(conversation_id, role, content, meta, created_at) VALUES (?, ?, ?, ?, ?)",
                           (conversation_id, role, content, (meta or "")[:500] or None, created))
        conn.execute("DELETE FROM chat_messages WHERE conversation_id = ? AND id NOT IN "
                     "(SELECT id FROM chat_messages WHERE conversation_id = ? ORDER BY id DESC LIMIT ?)",
                     (conversation_id, conversation_id, MAX_CHAT_MESSAGES))
    return {"id": cur.lastrowid, "role": role, "content": content, "meta": meta, "created_at": created}


def clear_chat(conn: sqlite3.Connection, conversation_id: str) -> int:
    with conn:
        return conn.execute("DELETE FROM chat_messages WHERE conversation_id = ?", (conversation_id,)).rowcount


# --- export / backup ---------------------------------------------------------

def export_all(conn: sqlite3.Connection) -> dict:
    return {
        "format": "atlas-os-export",
        "version": 1,
        "exported_at": _now(),
        "settings": {"memory_enabled": get_memory_enabled(conn), "retention": get_retention(conn)},
        "memories": list_memories(conn, limit=MAX_MEMORIES),
        "chat": {cid: list_chat(conn, cid, MAX_CHAT_MESSAGES) for (cid,) in
                 conn.execute("SELECT DISTINCT conversation_id FROM chat_messages").fetchall()},
    }


def backup(destination: Path | None = None) -> Path:
    """Consistent online copy using SQLite's backup API."""
    destination = destination or data_dir() / "backups" / f"atlas-{datetime.now(UTC).strftime('%Y%m%dT%H%M%SZ')}.db"
    destination.parent.mkdir(parents=True, exist_ok=True)
    src = _connect()
    try:
        dst = sqlite3.connect(destination)
        try:
            src.backup(dst)
        finally:
            dst.close()
    finally:
        src.close()
    return destination


def restore(source: Path) -> None:
    """Replace the live database with a backup after checking it is a valid ATLAS database."""
    check = sqlite3.connect(f"file:{source}?mode=ro", uri=True)
    try:
        if check.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
            raise StorageError(400, "corrupt_backup", "Backup failed SQLite integrity check.")
        tables = {r[0] for r in check.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        if not {"memories", "chat_messages", "settings"} <= tables:
            raise StorageError(400, "not_atlas_backup", "File is not an ATLAS OS database.")
        dst = _connect()
        try:
            check.backup(dst)
        finally:
            dst.close()
    finally:
        check.close()


def _main(argv: list[str]) -> int:
    if argv[:1] == ["path"]:
        print(db_path())
        return 0
    if argv[:1] == ["backup"]:
        print(backup(Path(argv[1]) if len(argv) > 1 else None))
        return 0
    if argv[:1] == ["restore"] and len(argv) == 2:
        restore(Path(argv[1]))
        print("restored", db_path())
        return 0
    if argv[:1] == ["export"]:
        with connection() as conn:
            print(json.dumps(export_all(conn), indent=2, ensure_ascii=False))
        return 0
    print(__doc__)
    return 2


if __name__ == "__main__":
    sys.exit(_main(sys.argv[1:]))
