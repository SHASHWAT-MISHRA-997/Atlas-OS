"""Optional local speech-to-text (app/stt.py).

The speech engine is replaced by a MOCK here (FakeWhisper): no real model can be downloaded in CI,
so these tests check the plumbing, limits and permissions, not recognition quality.
"""
import sys
import time
import types

import pytest
from fastapi.testclient import TestClient

from app import devices, stt
from app.main import create_app


class FakeSegment:
    def __init__(self, text):
        self.text = text


class FakeWhisper:  # MOCK of faster_whisper.WhisperModel
    loads = 0

    def __init__(self, path, device, compute_type):
        FakeWhisper.loads += 1
        self.path = path

    def transcribe(self, audio, language=None, beam_size=1, vad_filter=True):
        data = audio.read()
        if data.startswith(b"BAD"):
            raise ValueError("cannot decode")
        duration = 200.0 if data.startswith(b"LONG") else 1.5
        info = types.SimpleNamespace(language=language or "hi", duration=duration)
        return iter([FakeSegment(" namaste "), FakeSegment("ATLAS ")]), info


@pytest.fixture
def engine(tmp_path, monkeypatch):
    monkeypatch.setenv("ATLAS_DATA_DIR", str(tmp_path / "data"))
    downloads = []

    def download_model(size, output_dir):  # MOCK: writes a placeholder instead of downloading
        downloads.append(size)
        (stt.Path(output_dir) / "model.bin").write_bytes(b"mock")

    fake = types.ModuleType("faster_whisper")
    fake.WhisperModel, fake.download_model = FakeWhisper, download_model
    monkeypatch.setitem(sys.modules, "faster_whisper", fake)
    monkeypatch.setattr(stt, "engine_installed", lambda: True)
    stt._loaded.clear()
    stt._download.update(size=None, running=False, error=None, finished_at=None)
    return downloads


@pytest.fixture
def api():
    with TestClient(create_app()) as c:
        yield c


def wait_download(api):
    for _ in range(100):
        s = api.get("/api/voice/status").json()
        if not s["download"]["running"]:
            return s
        time.sleep(0.02)
    raise AssertionError("download did not finish")


def test_nothing_is_installed_or_downloaded_by_default(api, tmp_path, monkeypatch):
    monkeypatch.setenv("ATLAS_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setattr(stt, "engine_installed", lambda: False)
    s = api.get("/api/voice/status").json()
    assert s["models"] == [] and s["engine_installed"] is False
    r = api.post("/api/voice/transcribe", content=b"audio")
    assert r.status_code == 409 and "not installed" in r.json()["detail"]
    assert api.post("/api/voice/download", json={"size": "tiny", "confirm": True}).status_code == 409


def test_download_needs_confirmation_and_a_known_size(api, engine):
    r = api.post("/api/voice/download", json={"size": "tiny"})
    assert r.status_code == 400 and "75 MB" in r.json()["detail"]
    assert api.post("/api/voice/download", json={"size": "large-v3", "confirm": True}).status_code == 422
    assert engine == []


def test_download_then_transcribe_locally(api, engine):
    assert api.post("/api/voice/transcribe", content=b"audio").status_code == 409  # no model yet
    assert api.post("/api/voice/download", json={"size": "tiny", "confirm": True}).status_code == 202
    s = wait_download(api)
    assert engine == ["tiny"] and s["models"] == ["tiny"] and s["download"]["error"] is None
    r = api.post("/api/voice/transcribe?language=hi", content=b"webm-bytes", headers={"content-type": "audio/webm"})
    assert r.status_code == 200
    body = r.json()
    assert body["text"] == "namaste ATLAS" and body["language"] == "hi" and body["local"] is True
    api.post("/api/voice/transcribe", content=b"again")
    assert FakeWhisper.loads >= 1 and len(stt._loaded) == 1  # the model is loaded once and reused


def test_audio_limits_and_bad_audio(api, engine):
    api.post("/api/voice/download", json={"size": "tiny", "confirm": True})
    wait_download(api)
    assert api.post("/api/voice/transcribe", content=b"x" * (stt.MAX_AUDIO_BYTES + 1)).status_code == 413
    assert api.post("/api/voice/transcribe", content=b"LONG recording").status_code == 413
    assert api.post("/api/voice/transcribe", content=b"BAD").status_code == 422
    assert api.post("/api/voice/transcribe", content=b"").status_code == 422
    assert api.post("/api/voice/transcribe?language=fr", content=b"ok").status_code == 422


def test_failed_download_is_reported(api, engine, monkeypatch):
    def broken(size, output_dir):
        raise OSError("network unreachable")
    monkeypatch.setattr(sys.modules["faster_whisper"], "download_model", broken)
    api.post("/api/voice/download", json={"size": "base", "confirm": True})
    s = wait_download(api)
    assert "network unreachable" in s["download"]["error"] and s["models"] == []


def test_paired_phone_cannot_start_a_download(engine, monkeypatch):
    monkeypatch.setenv("ATLAS_AUTH_REQUIRED", "true")
    monkeypatch.delenv("ATLAS_ALLOWED_HOSTS", raising=False)
    devices._pending.clear()
    owner = TestClient(create_app(), base_url="http://127.0.0.1:8000", client=("127.0.0.1", 50000))
    owner.get("/")
    code = owner.post("/api/devices/pairing", json={"name": "Phone"}).json()["code"]
    phone = TestClient(create_app(), base_url="http://127.0.0.1:8000", client=("192.168.1.50", 50000))
    phone.get(f"/?pair={code}", follow_redirects=False)
    assert phone.get("/api/voice/status").status_code == 200  # signed in as a paired device
    assert phone.post("/api/voice/download", json={"size": "tiny", "confirm": True}).status_code == 403
    assert engine == []
