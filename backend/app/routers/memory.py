"""User-controlled memory and chat history stored in local SQLite (see app/storage.py)."""
from __future__ import annotations

from typing import Literal

from fastapi import APIRouter, Query
from pydantic import BaseModel, Field

from .. import storage

router = APIRouter(tags=["memory"])

ConversationId = Query(default="default", min_length=1, max_length=64, pattern=r"^[A-Za-z0-9_-]+$")


class MemoryIn(BaseModel):
    text: str = Field(min_length=1, max_length=storage.MAX_MEMORY_CHARS)


class Confirm(BaseModel):
    confirm: bool = False


class MemorySettings(BaseModel):
    enabled: bool


class ImportItem(BaseModel):
    text: str = Field(min_length=1, max_length=storage.MAX_MEMORY_CHARS)
    created_at: str | None = Field(default=None, max_length=40)
    createdAt: str | None = Field(default=None, max_length=40)  # browser-export field name


class ImportRequest(BaseModel):
    memories: list[ImportItem] = Field(max_length=storage.MAX_MEMORIES)


class ChatMessageIn(BaseModel):
    role: Literal["user", "assistant"]
    content: str = Field(min_length=1, max_length=storage.MAX_CHAT_CHARS)
    meta: str | None = Field(default=None, max_length=500)


def _require_confirm(body: Confirm) -> None:
    if not body.confirm:
        raise storage.StorageError(400, "confirm_required", "Send {\"confirm\": true} to delete everything.")


@router.get("/api/memory")
def list_memories(q: str | None = Query(default=None, max_length=200), limit: int = Query(default=200, ge=1, le=1000)):
    with storage.connection() as conn:
        return {"enabled": storage.get_memory_enabled(conn), "count": storage.count_memories(conn),
                "memories": storage.list_memories(conn, q, limit)}


@router.post("/api/memory", status_code=201)
def add_memory(body: MemoryIn):
    with storage.connection() as conn:
        return storage.add_memory(conn, body.text)


@router.patch("/api/memory/{memory_id}")
def update_memory(memory_id: str, body: MemoryIn):
    with storage.connection() as conn:
        return storage.update_memory(conn, memory_id, body.text)


@router.delete("/api/memory/{memory_id}", status_code=204)
def delete_memory(memory_id: str):
    with storage.connection() as conn:
        storage.delete_memory(conn, memory_id)


@router.post("/api/memory/clear")
def clear_memories(body: Confirm):
    _require_confirm(body)
    with storage.connection() as conn:
        return {"deleted": storage.delete_all_memories(conn)}


@router.put("/api/memory/settings")
def put_memory_settings(body: MemorySettings):
    with storage.connection() as conn:
        storage.set_memory_enabled(conn, body.enabled)
        return {"enabled": storage.get_memory_enabled(conn)}


@router.post("/api/memory/import")
def import_memories(body: ImportRequest):
    items = [{"text": m.text, "created_at": m.created_at or m.createdAt} for m in body.memories]
    with storage.connection() as conn:
        return storage.import_memories(conn, items)


@router.get("/api/storage/export")
def export_all():
    with storage.connection() as conn:
        return storage.export_all(conn)


@router.post("/api/storage/backup")
def make_backup():
    with storage.connection():
        pass  # raises if storage is disabled
    path = storage.backup()
    return {"file": path.name, "directory": str(path.parent), "bytes": path.stat().st_size}


@router.get("/api/chat/history")
def chat_history(conversation: str = ConversationId, limit: int = Query(default=40, ge=1, le=500)):
    with storage.connection() as conn:
        return {"conversation": conversation, "messages": storage.list_chat(conn, conversation, limit)}


@router.post("/api/chat/history", status_code=201)
def append_chat(body: ChatMessageIn, conversation: str = ConversationId):
    with storage.connection() as conn:
        return storage.append_chat(conn, conversation, body.role, body.content, body.meta)


@router.post("/api/chat/history/clear")
def clear_chat(body: Confirm, conversation: str = ConversationId):
    _require_confirm(body)
    with storage.connection() as conn:
        return {"deleted": storage.clear_chat(conn, conversation)}
