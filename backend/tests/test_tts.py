"""Optional local read-aloud (app/tts.py).

Piper is replaced by a MOCK (FakePiperVoice writes a short silent WAV): no real voice can be
downloaded in CI, so these tests check the plumbing, limits and permissions, not speech quality.
"""
import io
import sys
import time
import types
import wave

import pytest
from fastapi.testclient import TestClient

from app import devices, tts
from app.main import create_app


class FakePiperVoice:  # MOCK of piper.PiperVoice
    @classmethod
    def load(cls, path):
        return cls()

    def synthesize_wav(self, text, wav):
        wav.setnchannels(1)
        wav.setsampwidth(2)
        wav.setframerate(22050)
        wav.writeframes(b"\x00\x00" * 2205)


@pytest.fixture
def engine(tmp_path, monkeypatch):
    monkeypatch.setenv("ATLAS_DATA_DIR", str(tmp_path / "data"))
    downloads = []

    def download_voice(voice, download_dir):  # MOCK: placeholder files instead of a download
        downloads.append(voice)
        (download_dir / f"{voice}.onnx").write_bytes(b"mock")
        (download_dir / f"{voice}.onnx.json").write_text("{}")

    piper = types.ModuleType("piper")
    piper.PiperVoice = FakePiperVoice
    dl = types.ModuleType("piper.download_voices")
    dl.download_voice = download_voice
    monkeypatch.setitem(sys.modules, "piper", piper)
    monkeypatch.setitem(sys.modules, "piper.download_voices", dl)
    monkeypatch.setattr(tts, "engine_installed", lambda: True)
    tts._loaded.clear()
    tts._download.update(voice=None, running=False, error=None, finished_at=None)
    return downloads


@pytest.fixture
def api():
    with TestClient(create_app()) as c:
        yield c


def wait(api):
    for _ in range(100):
        s = api.get("/api/voice/tts/status").json()
        if not s["download"]["running"]:
            return s
        time.sleep(0.02)
    raise AssertionError("download did not finish")


def test_off_until_installed(api, tmp_path, monkeypatch):
    monkeypatch.setenv("ATLAS_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setattr(tts, "engine_installed", lambda: False)
    assert api.get("/api/voice/tts/status").json()["voices"] == []
    r = api.post("/api/voice/tts/speak", json={"text": "namaste"})
    assert r.status_code == 409 and "not installed" in r.json()["detail"]


def test_download_needs_confirmation_and_a_listed_voice(api, engine):
    assert api.post("/api/voice/tts/download", json={"voice": "en_US-lessac-medium"}).status_code == 400
    assert api.post("/api/voice/tts/download", json={"voice": "../../evil", "confirm": True}).status_code == 422
    assert engine == []


def test_download_then_speak_locally(api, engine):
    assert api.post("/api/voice/tts/speak", json={"text": "hello"}).status_code == 409  # no voice yet
    assert api.post("/api/voice/tts/download", json={"voice": "hi_IN-pratham-medium", "confirm": True}).status_code == 202
    s = wait(api)
    assert engine == ["hi_IN-pratham-medium"] and s["voices"] == ["hi_IN-pratham-medium"]
    r = api.post("/api/voice/tts/speak", json={"text": "namaste ATLAS"})
    assert r.status_code == 200 and r.headers["content-type"] == "audio/wav" and r.headers["cache-control"] == "no-store"
    with wave.open(io.BytesIO(r.content)) as w:
        assert w.getframerate() == 22050 and w.getnframes() == 2205


def test_text_limits(api, engine):
    api.post("/api/voice/tts/download", json={"voice": "en_US-lessac-medium", "confirm": True})
    wait(api)
    assert api.post("/api/voice/tts/speak", json={"text": "   "}).status_code == 422
    assert api.post("/api/voice/tts/speak", json={"text": "a" * (tts.MAX_TEXT_CHARS + 1)}).status_code == 413
    assert api.post("/api/voice/tts/speak", json={"text": "hi", "voice": "en_GB-alan-medium"}).status_code == 409


def test_broken_download_is_not_installed(api, engine, monkeypatch):
    def half(voice, download_dir):
        (download_dir / f"{voice}.onnx").write_bytes(b"partial")
        raise OSError("connection reset")
    monkeypatch.setattr(sys.modules["piper.download_voices"], "download_voice", half)
    api.post("/api/voice/tts/download", json={"voice": "en_US-lessac-medium", "confirm": True})
    s = wait(api)
    assert "connection reset" in s["download"]["error"] and s["voices"] == []
    assert not (tts.voices_dir() / "en_US-lessac-medium.onnx").exists()


def test_paired_phone_cannot_download_voices(engine, monkeypatch):
    monkeypatch.setenv("ATLAS_AUTH_REQUIRED", "true")
    monkeypatch.delenv("ATLAS_ALLOWED_HOSTS", raising=False)
    devices._pending.clear()
    owner = TestClient(create_app(), base_url="http://127.0.0.1:8000", client=("127.0.0.1", 50000))
    owner.get("/")
    code = owner.post("/api/devices/pairing", json={"name": "Phone"}).json()["code"]
    phone = TestClient(create_app(), base_url="http://127.0.0.1:8000", client=("192.168.1.50", 50000))
    phone.get(f"/?pair={code}", follow_redirects=False)
    assert phone.get("/api/voice/tts/status").status_code == 200
    assert phone.post("/api/voice/tts/download", json={"voice": "en_US-lessac-medium", "confirm": True}).status_code == 403
    assert engine == []
