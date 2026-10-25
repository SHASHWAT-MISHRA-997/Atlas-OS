"""Document search over the local index built by approved ``index_documents`` tasks (app/docsearch.py)."""
from __future__ import annotations

from fastapi import APIRouter, Query
from pydantic import BaseModel

from .. import docsearch, storage

router = APIRouter(prefix="/api/docs", tags=["documents"])


class ClearRequest(BaseModel):
    confirm: bool = False
    folder: str | None = None


@router.get("/status")
def docs_status():
    return docsearch.status()


@router.get("/search")
def docs_search(q: str = Query(min_length=1, max_length=500), limit: int = Query(default=5, ge=1, le=20),
                folder: str | None = Query(default=None, max_length=40)):
    return {"query": q, "results": docsearch.search(q, limit, folder)}


@router.post("/clear")
def docs_clear(body: ClearRequest):
    if not body.confirm:
        raise storage.StorageError(400, "confirm_required", "Send {\"confirm\": true} to delete the document index.")
    return {"removed_files": docsearch.clear(body.folder)}
