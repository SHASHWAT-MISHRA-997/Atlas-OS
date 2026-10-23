"""Per-device credentials for phones, tablets and other computers.

The install token (app/auth.py) belongs to the machine running ATLAS. Other
devices never receive it. Instead the owner creates a one-time pairing code,
and opening ``/?pair=<code>`` on the device swaps it for that device's own
random token. Each device can be listed and revoked on its own, so losing a
phone does not mean rotating everything.

Only SHA-256 hashes of device tokens and pairing codes are kept. Device records
live in ``devices.json`` (0600) next to the install token, not in the SQLite
database, so pairing still works when server storage is disabled.

Pairing codes are held in memory only: they expire after PAIRING_TTL_SECONDS,
work once, and are lost on restart.
"""
from __future__ import annotations

import hashlib
import hmac
import json
import os
import secrets
import threading
import time
import uuid
from datetime import UTC, datetime
from pathlib import Path

from . import storage

MAX_DEVICES = 20
MAX_PENDING_CODES = 5
PAIRING_TTL_SECONDS = 600
LAST_SEEN_RESOLUTION_SECONDS = 300
NAME_MAX = 40

_lock = threading.Lock()
_pending: dict[str, tuple[float, str]] = {}  # code hash -> (expires monotonic, device name)


class DeviceError(Exception):
    def __init__(self, status_code: int, code: str, message: str):
        super().__init__(message)
        self.status_code = status_code
        self.code = code
        self.message = message


def _hash(secret: str) -> str:
    return hashlib.sha256(secret.encode()).hexdigest()


def _now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


def devices_path() -> Path:
    return storage.data_dir() / "devices.json"


def _load() -> list[dict]:
    try:
        data = json.loads(devices_path().read_text(encoding="utf-8"))
    except FileNotFoundError:
        return []
    except (OSError, ValueError) as exc:
        # Fail closed: an unreadable file means no device is trusted.
        raise DeviceError(500, "devices_unreadable", "Device list is unreadable; re-pair devices after fixing it.") from exc
    return [d for d in data.get("devices", []) if isinstance(d, dict) and "token_sha256" in d]


def _save(devices: list[dict]) -> None:
    path = devices_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as fh:
        json.dump({"version": 1, "devices": devices}, fh, indent=1)
    os.replace(tmp, path)


def _public(device: dict) -> dict:
    return {k: device.get(k) for k in ("id", "name", "created_at", "last_seen_at", "revoked_at")}


def clean_name(name: str | None) -> str:
    cleaned = " ".join((name or "").split())[:NAME_MAX]
    return cleaned or "Paired device"


def create_pairing_code(name: str | None = None) -> dict:
    code = secrets.token_urlsafe(18)
    with _lock:
        now = time.monotonic()
        for key in [k for k, (exp, _) in _pending.items() if exp <= now]:
            del _pending[key]
        if len(_pending) >= MAX_PENDING_CODES:
            raise DeviceError(429, "too_many_codes", "Too many unused pairing codes. Wait a few minutes or use one.")
        _pending[_hash(code)] = (now + PAIRING_TTL_SECONDS, clean_name(name))
    return {"code": code, "expires_in": PAIRING_TTL_SECONDS}


def redeem_pairing_code(code: str) -> str | None:
    """Return the device name if ``code`` is a live pairing code, consuming it."""
    with _lock:
        entry = _pending.pop(_hash(code), None)
    if entry is None or entry[0] <= time.monotonic():
        return None
    return entry[1]


def register(name: str | None) -> tuple[dict, str]:
    """Create a device and return (record, plaintext token). The token is shown exactly once."""
    token = secrets.token_urlsafe(32)
    with _lock:
        devices = _load()
        active = [d for d in devices if not d.get("revoked_at")]
        if len(active) >= MAX_DEVICES:
            raise DeviceError(409, "too_many_devices", f"At most {MAX_DEVICES} devices can be paired. Revoke one first.")
        record = {"id": uuid.uuid4().hex[:12], "name": clean_name(name), "token_sha256": _hash(token),
                  "created_at": _now(), "last_seen_at": None, "revoked_at": None}
        # Keep revoked entries briefly for the audit trail, but cap file growth.
        devices = active + [d for d in devices if d.get("revoked_at")][-MAX_DEVICES:] + [record]
        _save(devices)
    return _public(record), token


def authenticate(token: str | None) -> dict | None:
    """Return the active device for ``token``, or None."""
    if not token:
        return None
    digest = _hash(token)
    match = None
    for device in _load():
        # Compare every entry so timing does not reveal which one matched.
        if hmac.compare_digest(device["token_sha256"], digest) and not device.get("revoked_at"):
            match = device
    if match is not None:
        _touch(match["id"], match.get("last_seen_at"))
    return _public(match) if match else None


def _touch(device_id: str, last_seen: str | None) -> None:
    if last_seen:
        try:
            age = (datetime.now(UTC) - datetime.fromisoformat(last_seen)).total_seconds()
            if age < LAST_SEEN_RESOLUTION_SECONDS:
                return
        except ValueError:
            pass
    with _lock:
        devices = _load()
        for device in devices:
            if device["id"] == device_id:
                device["last_seen_at"] = _now()
        _save(devices)


def list_devices(include_revoked: bool = False) -> list[dict]:
    return [_public(d) for d in _load() if include_revoked or not d.get("revoked_at")]


def revoke(device_id: str) -> dict:
    with _lock:
        devices = _load()
        for device in devices:
            if device["id"] == device_id and not device.get("revoked_at"):
                device["revoked_at"] = _now()
                _save(devices)
                return _public(device)
    raise DeviceError(404, "device_not_found", "No active device with that id.")


def revoke_all() -> int:
    with _lock:
        devices = _load()
        count = 0
        for device in devices:
            if not device.get("revoked_at"):
                device["revoked_at"] = _now()
                count += 1
        if count:
            _save(devices)
        _pending.clear()
    return count
