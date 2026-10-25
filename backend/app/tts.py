"""Optional local read-aloud with Piper (Milestone D).

Off until the owner installs the engine (``pip install -r requirements-voice.txt``) and downloads a
voice from AI Chat → Model settings on the PC. Nothing is downloaded automatically. Text is turned
into speech on this machine and the audio is not stored.
"""
from __future__ import annotations

import importlib.util
import io
import shutil
import tempfile
import threading
import time
import wave
from pathlib import Path

from . import storage

# Approximate sizes of Piper "medium" voices (rhasspy/piper-voices on Hugging Face).
VOICES = {
    "en_US-lessac-medium": {"label": "English (US) · Lessac", "approx_mb": 63},
    "en_GB-alan-medium": {"label": "English (UK) · Alan", "approx_mb": 63},
    "hi_IN-pratham-medium": {"label": "Hindi · Pratham", "approx_mb": 63},
}
MAX_TEXT_CHARS = 5000


class TtsError(Exception):
    def __init__(self, status: int, code: str, message: str):
        super().__init__(message)
        self.status, self.code, self.message = status, code, message


_lock = threading.Lock()
_download: dict = {"voice": None, "running": False, "error": None, "finished_at": None}
_loaded: dict = {}


def engine_installed() -> bool:
    return importlib.util.find_spec("piper") is not None


def voices_dir() -> Path:
    return storage.data_dir() / "models" / "piper"


def installed_voices() -> list[str]:
    d = voices_dir()
    return [v for v in VOICES if (d / f"{v}.onnx").is_file() and (d / f"{v}.onnx.json").is_file()]


def status() -> dict:
    with _lock:
        download = dict(_download)
    return {"engine_installed": engine_installed(), "voices": installed_voices(),
            "available": [{"voice": v, **meta} for v, meta in VOICES.items()], "download": download}


def _download_worker(voice: str) -> None:
    error = None
    try:
        from piper.download_voices import download_voice
        target = voices_dir()
        target.mkdir(parents=True, exist_ok=True)
        # Download into a scratch folder first, so a broken download never looks like an installed voice.
        with tempfile.TemporaryDirectory(dir=target) as scratch:
            download_voice(voice, Path(scratch))
            for suffix in (".onnx.json", ".onnx"):  # the model last: it marks the voice as installed
                shutil.move(str(Path(scratch) / f"{voice}{suffix}"), str(target / f"{voice}{suffix}"))
    except Exception as exc:  # noqa: BLE001 - reported to the user as text
        error = f"Download failed: {exc.__class__.__name__}: {str(exc)[:300]}"
    with _lock:
        _download.update(running=False, error=error, finished_at=time.time())


def start_download(voice: str) -> dict:
    if voice not in VOICES:
        raise TtsError(422, "unknown_voice", "Unknown voice.")
    if not engine_installed():
        raise TtsError(409, "engine_missing", "Install the voice engine first: pip install -r requirements-voice.txt")
    with _lock:
        if _download["running"]:
            raise TtsError(409, "download_running", "A voice download is already running.")
        _download.update(voice=voice, running=True, error=None, finished_at=None)
    threading.Thread(target=_download_worker, args=(voice,), daemon=True, name="atlas-tts-download").start()
    return status()


def _voice(name: str):
    with _lock:
        if name not in _loaded:
            from piper import PiperVoice
            _loaded[name] = PiperVoice.load(voices_dir() / f"{name}.onnx")
        return _loaded[name]


def speak(text: str, voice: str | None = None) -> bytes:
    """Returns a WAV file."""
    if not engine_installed():
        raise TtsError(409, "engine_missing", "Local read-aloud is not installed on this PC.")
    text = (text or "").strip()
    if not text:
        raise TtsError(422, "no_text", "Nothing to read.")
    if len(text) > MAX_TEXT_CHARS:
        raise TtsError(413, "text_too_long", f"Read-aloud takes at most {MAX_TEXT_CHARS:,} characters at a time.")
    voices = installed_voices()
    voice = voice or (voices[0] if voices else None)
    if voice not in voices:
        raise TtsError(409, "no_voice", "That voice is not downloaded. Download one in AI Chat → Model settings on the PC.")
    buffer = io.BytesIO()
    with wave.open(buffer, "wb") as wav:
        _voice(voice).synthesize_wav(text, wav)
    return buffer.getvalue()
