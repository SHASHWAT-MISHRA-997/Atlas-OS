"""Local API authentication.

ATLAS is a single-user app, so there are no accounts. Instead each install has
one random API token, and every /api/ request must prove it knows the token:

* A browser on the same machine (loopback address) that loads ``/`` receives it
  as an HttpOnly, SameSite=Strict cookie, so the UI just works.
* Any other device is paired once through ``/?pair=<code>`` and gets its own
  revocable device token (see app/devices.py). The code comes from the Devices
  panel, or the install token itself works as a code (``python -m app.auth
  token``). Either way the device never stores the install token.
* Scripts can send ``Authorization: Bearer <token>`` (install or device token).

Each request records who made it in ``scope["state"]["principal"]``:
``{"kind": "owner"}`` for the install token, or ``{"kind": "device", ...}``.

The middleware also rejects unknown Host headers (DNS-rebinding protection) and
cross-origin state-changing requests (CSRF protection).

CLI (from backend/):  python -m app.auth token | rotate | devices | revoke <id> | revoke-all
"""
from __future__ import annotations

import hmac
import json
import os
import secrets
import sys
from http.cookies import SimpleCookie
from pathlib import Path
from urllib.parse import urlparse

from . import devices, storage

COOKIE = "atlas_session"
PUBLIC_PATHS = {"/", "/health", "/favicon.ico", "/sw.js"}
PUBLIC_PREFIXES = ("/static/",)
LOOPBACK = {"127.0.0.1", "::1", "localhost"}
SAFE_METHODS = {"GET", "HEAD", "OPTIONS"}


def auth_required() -> bool:
    raw = (os.getenv("ATLAS_AUTH_REQUIRED") or "true").strip().lower()
    return raw not in {"0", "false", "no", "off"}


def token_path() -> Path:
    return storage.data_dir() / "api_token"


def get_token() -> str:
    """Operator override via ATLAS_API_TOKEN, else a per-install random token on disk."""
    env = (os.getenv("ATLAS_API_TOKEN") or "").strip()
    if env:
        return env
    path = token_path()
    try:
        token = path.read_text(encoding="utf-8").strip()
        if len(token) >= 32:
            return token
    except FileNotFoundError:
        pass
    return rotate_token()


def rotate_token() -> str:
    path = token_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    token = secrets.token_urlsafe(32)
    tmp = path.with_suffix(".tmp")
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as fh:
        fh.write(token)
    os.replace(tmp, path)
    return token


def token_matches(candidate: str | None) -> bool:
    return bool(candidate) and hmac.compare_digest(candidate.encode(), get_token().encode())


OWNER = {"kind": "owner"}


def identify(token: str | None) -> dict | None:
    """Who a presented token belongs to: the owner (install token), an active device, or nobody."""
    if token_matches(token):
        return dict(OWNER)
    try:
        device = devices.authenticate(token)
    except devices.DeviceError:
        return None  # fail closed
    return {"kind": "device", "id": device["id"], "name": device["name"]} if device else None


def allowed_hosts() -> set[str]:
    extra = {h.strip().lower() for h in (os.getenv("ATLAS_ALLOWED_HOSTS") or "").split(",") if h.strip()}
    return LOOPBACK | extra


def is_loopback(host: str | None) -> bool:
    return (host or "") in LOOPBACK


PROXY_HEADERS = ("x-forwarded-for", "forwarded", "x-real-ip", "x-forwarded-host", "tailscale-user-login",
                 "cf-connecting-ip", "true-client-ip")


def is_same_computer(client_host: str | None, headers) -> bool:
    """True only for a browser on the machine running ATLAS, talking to it directly.

    A reverse proxy or tunnel on this machine (Tailscale Serve, cloudflared, nginx) also connects
    from 127.0.0.1, so loopback alone is not enough: the Host must be a loopback name and no
    forwarding headers may be present. Otherwise every remote visitor would become the owner.
    """
    if not is_loopback(client_host):
        return False
    if any(name in headers for name in PROXY_HEADERS):
        return False
    return _host_only(headers.get("host", "")) in LOOPBACK


def _host_only(value: str) -> str:
    value = value.strip().lower()
    if value.startswith("["):  # [::1]:8000
        return value[1:value.find("]")] if "]" in value else value
    return value.rsplit(":", 1)[0] if value.count(":") == 1 else value


def session_cookie_header(token: str, secure: bool = False) -> str:
    return f"{COOKIE}={token}; Path=/; HttpOnly; SameSite=Strict" + ("; Secure" if secure else "")


def clear_cookie_header() -> str:
    return f"{COOKIE}=; Path=/; HttpOnly; SameSite=Strict; Max-Age=0"


class AuthMiddleware:
    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            return await self.app(scope, receive, send)
        headers = {k.decode("latin-1").lower(): v.decode("latin-1") for k, v in scope.get("headers", [])}
        path = scope.get("path", "")
        method = scope.get("method", "GET")

        host = _host_only(headers.get("host", ""))
        if host not in allowed_hosts():
            return await _deny(send, 421, "unknown_host",
                               "Unknown Host header. Add it to ATLAS_ALLOWED_HOSTS if you really serve ATLAS under that name.")

        origin = headers.get("origin")
        if origin and method not in SAFE_METHODS:
            parsed = urlparse(origin)
            if parsed.hostname is None or _host_only(parsed.netloc) != host:
                return await _deny(send, 403, "cross_origin", "Cross-origin requests are not allowed.")

        state = scope.setdefault("state", {})
        if not auth_required():
            state["principal"] = dict(OWNER)
            return await self.app(scope, receive, send)
        if path in PUBLIC_PATHS or path.startswith(PUBLIC_PREFIXES):
            return await self.app(scope, receive, send)

        bearer = headers.get("authorization", "")
        presented = bearer[7:].strip() if bearer.lower().startswith("bearer ") else None
        if presented is None and "cookie" in headers:
            jar = SimpleCookie()
            try:
                jar.load(headers["cookie"])
            except Exception:  # noqa: BLE001 - malformed cookie header means "no session"
                jar = SimpleCookie()
            presented = jar[COOKIE].value if COOKIE in jar else None
        principal = identify(presented)
        if principal is None:
            return await _deny(send, 401, "unauthorized",
                               "Not signed in to this ATLAS install. Open ATLAS on the computer running it, or pair this "
                               "device with a link from Settings → Devices there.")
        state["principal"] = principal
        return await self.app(scope, receive, send)


async def _deny(send, status: int, code: str, message: str):
    body = json.dumps({"detail": message, "code": code}).encode()
    await send({"type": "http.response.start", "status": status,
                "headers": [(b"content-type", b"application/json"), (b"content-length", str(len(body)).encode()),
                            (b"cache-control", b"no-store")]})
    await send({"type": "http.response.body", "body": body})


def _main(argv: list[str]) -> int:
    if argv[:1] == ["token"]:
        token = get_token()
        print(token)
        print(f"Pair another device by opening: http://<this-computer>:8000/?pair={token}", file=sys.stderr)
        return 0
    if argv[:1] == ["rotate"]:
        rotate_token()
        revoked = devices.revoke_all()
        print(f"New install token written and {revoked} paired device(s) revoked. Restart is not needed.", file=sys.stderr)
        return 0
    if argv[:1] == ["devices"]:
        for d in devices.list_devices():
            print(f"{d['id']}  {d['name']}  paired {d['created_at']}  last seen {d['last_seen_at'] or 'never'}")
        return 0
    if argv[:1] == ["revoke"] and len(argv) == 2:
        try:
            devices.revoke(argv[1])
        except devices.DeviceError as exc:
            print(exc.message, file=sys.stderr)
            return 1
        print("Device revoked.", file=sys.stderr)
        return 0
    if argv[:1] == ["revoke-all"]:
        print(f"{devices.revoke_all()} device(s) revoked.", file=sys.stderr)
        return 0
    print(__doc__)
    return 2


if __name__ == "__main__":
    sys.exit(_main(sys.argv[1:]))
