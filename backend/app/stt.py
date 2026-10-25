"""Optional local speech-to-text with faster-whisper (Milestone D).

Off until the owner installs the engine (``pip install -r requirements-voice.txt``) and starts a
model download from the Voice settings on the PC. Nothing is downloaded automatically. Audio sent
to ``/api/voice/transcribe`` is decoded and transcribed on this machine and is not stored.
"""
from __future__ import annotations

import importlib.util
import io
import threading
import time
from pathlib import Path

from . import storage

# Approximate download sizes of the int8-ready CTranslate2 models (Systran/faster-whisper-*).
MODELS = {"tiny": 75, "base": 145, "small": 484}
MAX_AUDIO_BYTES = 10 * 1024 * 1024
MAX_AUDIO_SECONDS = 120
LANGUAGES = {"auto": None, "en": "en", "hi": "hi"}


class SttError(Exception):
    def __init__(self, status: int, code: str, message: str):
        super().__init__(message)
        self.status, self.code, self.message = status, code, message


_lock = threading.Lock()
_download: dict = {"size": None, "running": False, "error": None, "finished_at": None}
_loaded: dict = {}  # size -> WhisperModel


def engine_installed() -> bool:
    return importlib.util.find_spec("faster_whisper") is not None


def models_dir() -> Path:
    return storage.data_dir() / "models"


def model_path(size: str) -> Path:
    return models_dir() / f"whisper-{size}"


def installed_models() -> list[str]:
    return [s for s in MODELS if (model_path(s) / "model.bin").is_file()]


def status() -> dict:
    with _lock:
        download = dict(_download)
    return {"engine_installed": engine_installed(), "models": installed_models(),
            "available": [{"size": s, "approx_mb": mb} for s, mb in MODELS.items()],
            "download": download, "languages": list(LANGUAGES)}


def _download_worker(size: str) -> None:
    error = None
    try:
        from faster_whisper import download_model
        target = model_path(size)
        target.mkdir(parents=True, exist_ok=True)
        download_model(size, output_dir=str(target))
    except Exception as exc:  # noqa: BLE001 - reported to the user as text
        error = f"Download failed: {exc.__class__.__name__}: {str(exc)[:300]}"
    with _lock:
        _download.update(running=False, error=error, finished_at=time.time())


def start_download(size: str) -> dict:
    """Starts a model download the owner asked for. Returns immediately; poll status()."""
    if size not in MODELS:
        raise SttError(422, "unknown_model", "Choose tiny, base or small.")
    if not engine_installed():
        raise SttError(409, "engine_missing", "Install the voice engine first: pip install -r requirements-voice.txt")
    with _lock:
        if _download["running"]:
            raise SttError(409, "download_running", "A model download is already running.")
        _download.update(size=size, running=True, error=None, finished_at=None)
    threading.Thread(target=_download_worker, args=(size,), daemon=True, name="atlas-stt-download").start()
    return status()


def _model(size: str):
    with _lock:
        if size not in _loaded:
            from faster_whisper import WhisperModel
            _loaded[size] = WhisperModel(str(model_path(size)), device="cpu", compute_type="int8")
        return _loaded[size]


def transcribe(audio: bytes, language: str = "auto", size: str | None = None) -> dict:
    if not engine_installed():
        raise SttError(409, "engine_missing", "Local speech-to-text is not installed on this PC.")
    models = installed_models()
    size = size or (models[0] if models else None)
    if size not in models:
        raise SttError(409, "no_model", "No speech model is downloaded yet. Download one in AI Chat → Voice on the PC.")
    if language not in LANGUAGES:
        raise SttError(422, "unknown_language", "Language must be auto, en or hi.")
    if not audio:
        raise SttError(422, "no_audio", "No audio was received.")
    started = time.perf_counter()
    try:
        segments, info = _model(size).transcribe(io.BytesIO(audio), language=LANGUAGES[language], beam_size=1,
                                                 vad_filter=True)
        if info.duration > MAX_AUDIO_SECONDS:
            raise SttError(413, "audio_too_long", f"Recordings can be at most {MAX_AUDIO_SECONDS} seconds.")
        text = " ".join(s.text.strip() for s in segments).strip()
    except SttError:
        raise
    except Exception as exc:  # noqa: BLE001 - undecodable audio and similar
        raise SttError(422, "bad_audio", f"Could not read that recording ({exc.__class__.__name__}).") from None
    return {"text": text, "language": info.language, "duration_s": round(info.duration, 2), "model": size,
            "seconds": round(time.perf_counter() - started, 2), "local": True}
