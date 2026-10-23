"""Paired devices: create one-time pairing codes, list and revoke devices (see app/devices.py)."""
from __future__ import annotations

import os

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from .. import auth, devices

router = APIRouter(tags=["devices"])


class PairingRequest(BaseModel):
    name: str | None = Field(default=None, max_length=devices.NAME_MAX)


def principal(request: Request) -> dict:
    return request.scope.get("state", {}).get("principal") or {"kind": "anonymous"}


def require_owner(request: Request) -> None:
    if principal(request).get("kind") != "owner":
        raise devices.DeviceError(403, "owner_only", "Only the computer running ATLAS can manage paired devices.")


@router.get("/api/devices/current")
def current_device(request: Request):
    who = principal(request)
    return {"kind": who.get("kind"), "id": who.get("id"), "name": who.get("name")}


@router.delete("/api/devices/current")
def forget_current_device(request: Request):
    """Sign this device out for good (revokes its token) and clear its cookie."""
    who = principal(request)
    if who.get("kind") != "device":
        raise devices.DeviceError(400, "not_a_device", "This is the owner session; it cannot be forgotten.")
    devices.revoke(who["id"])
    response = JSONResponse({"revoked": who["id"]})
    response.headers["set-cookie"] = auth.clear_cookie_header()
    return response


@router.get("/api/devices")
def list_devices(request: Request):
    require_owner(request)
    return {"devices": devices.list_devices(), "max": devices.MAX_DEVICES}


@router.post("/api/devices/pairing", status_code=201)
def create_pairing(body: PairingRequest, request: Request):
    require_owner(request)
    result = devices.create_pairing_code(body.name)
    path = f"/?pair={result['code']}"
    # The server cannot know which address the other device should use, so a full
    # link is only offered when the operator configured one.
    public = (os.getenv("ATLAS_PUBLIC_URL") or "").strip().rstrip("/")
    return {**result, "path": path, "url": f"{public}{path}" if public else None}


@router.delete("/api/devices/{device_id}")
def revoke_device(device_id: str, request: Request):
    require_owner(request)
    return devices.revoke(device_id)
