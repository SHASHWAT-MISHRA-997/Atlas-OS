"""Optional local speech-to-text (app/stt.py). The browser's own dictation still works without it."""
from __future__ import annotations

import asyncio
from typing import Literal

from fastapi import APIRouter, HTTPException, Query, Request
from pydantic import BaseModel

from .. import stt

router = APIRouter(prefix="/api/voice", tags=["voice"])


class DownloadRequest(BaseModel):
    size: Literal["tiny", "base", "small"]
    confirm: bool = False


def _raise(exc: stt.SttError):
    raise HTTPException(status_code=exc.status, detail=exc.message)


@router.get("/status")
def voice_status():
    return stt.status()


@router.post("/download", status_code=202)
def voice_download(body: DownloadRequest, request: Request):
    principal = request.scope.get("state", {}).get("principal") or {}
    if principal.get("kind") == "device":
        raise HTTPException(status_code=403, detail="Only the PC running ATLAS can download speech models.")
    if not body.confirm:
        raise HTTPException(status_code=400, detail=f"Send confirm: true to download about {stt.MODELS[body.size]} MB.")
    try:
        return stt.start_download(body.size)
    except stt.SttError as exc:
        _raise(exc)


@router.post("/transcribe")
async def voice_transcribe(request: Request, language: str = Query(default="auto", max_length=8)):
    declared = int(request.headers.get("content-length") or 0)
    if declared > stt.MAX_AUDIO_BYTES:
        raise HTTPException(status_code=413, detail="Recording is too large (10 MB at most).")
    audio = bytearray()
    async for chunk in request.stream():
        audio.extend(chunk)
        if len(audio) > stt.MAX_AUDIO_BYTES:
            raise HTTPException(status_code=413, detail="Recording is too large (10 MB at most).")
    try:
        return await asyncio.to_thread(stt.transcribe, bytes(audio), language)
    except stt.SttError as exc:
        _raise(exc)
