"""Optional local speech-to-text (app/stt.py) and read-aloud (app/tts.py).

The browser's own dictation and voices still work without them."""
from __future__ import annotations

import asyncio
from typing import Literal

from fastapi import APIRouter, HTTPException, Query, Request, Response
from pydantic import BaseModel, Field

from .. import stt, tts

router = APIRouter(prefix="/api/voice", tags=["voice"])


class DownloadRequest(BaseModel):
    size: Literal["tiny", "base", "small"]
    confirm: bool = False


class VoiceDownloadRequest(BaseModel):
    voice: str = Field(max_length=60)
    confirm: bool = False


class SpeakRequest(BaseModel):
    text: str = Field(max_length=tts.MAX_TEXT_CHARS * 2)
    voice: str | None = Field(default=None, max_length=60)


def _owner_only(request: Request, what: str):
    principal = request.scope.get("state", {}).get("principal") or {}
    if principal.get("kind") == "device":
        raise HTTPException(status_code=403, detail=f"Only the PC running ATLAS can download {what}.")


def _raise(exc: stt.SttError | tts.TtsError):
    raise HTTPException(status_code=exc.status, detail=exc.message)


@router.get("/status")
def voice_status():
    return stt.status()


@router.post("/download", status_code=202)
def voice_download(body: DownloadRequest, request: Request):
    _owner_only(request, "speech models")
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


@router.get("/tts/status")
def tts_status():
    return tts.status()


@router.post("/tts/download", status_code=202)
def tts_download(body: VoiceDownloadRequest, request: Request):
    _owner_only(request, "voices")
    if body.voice not in tts.VOICES:
        raise HTTPException(status_code=422, detail="Unknown voice.")
    if not body.confirm:
        raise HTTPException(status_code=400, detail=f"Send confirm: true to download about {tts.VOICES[body.voice]['approx_mb']} MB.")
    try:
        return tts.start_download(body.voice)
    except tts.TtsError as exc:
        _raise(exc)


@router.post("/tts/speak")
async def tts_speak(body: SpeakRequest):
    try:
        audio = await asyncio.to_thread(tts.speak, body.text, body.voice)
    except tts.TtsError as exc:
        _raise(exc)
    return Response(content=audio, media_type="audio/wav", headers={"Cache-Control": "no-store"})
