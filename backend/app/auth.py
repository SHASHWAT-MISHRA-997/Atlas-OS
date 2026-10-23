"""Local API authentication.

ATLAS is a single-user app, so there are no accounts. Instead each install has
one random API token, and every /api/ request must prove it knows the token:

* A browser on the same machine (loopback address) that loads ``/`` receives it
  as an HttpOnly, SameSite=Strict cookie, so the UI just works.
* Any other device must open ``/?pair=<token>`` once. The token is shown by
  ``python -m app.auth token`` on the machine running ATLAS. It is never logged.
* Scripts can send ``Authorization: Bearer <token>``.

The middleware also rejects unknown Host headers (DNS-rebinding protection) and
cross-origin state-changing requests (CSRF protection).

CLI (from backend/):  python -m app.auth token | rotate
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

from . import storage

COOKIE = "atlas_session"
PUBLIC_PATHS = {"/", "/health", "/favicon.ico"}
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


def allowed_hosts() -> set[str]:
    extra = {h.strip().lower() for h in (os.getenv("ATLAS_ALLOWED_HOSTS") or "").split(",") if h.strip()}
    return LOOPBACK | extra


def is_loopback(host: str | None) -> bool:
    return (host or "") in LOOPBACK


def _host_only(value: str) -> str:
    value = value.strip().lower()
    if value.startswith("["):  # [::1]:8000
        return value[1:value.find("]")] if "]" in value else value
    return value.rsplit(":", 1)[0] if value.count(":") == 1 else value


def session_cookie_header(token: str) -> str:
    return f"{COOKIE}={token}; Path=/; HttpOnly; SameSite=Strict"


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

        if not auth_required() or path in PUBLIC_PATHS or path.startswith(PUBLIC_PREFIXES):
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
        if not token_matches(presented):
            return await _deny(send, 401, "unauthorized",
                               "Not signed in to this ATLAS install. Open ATLAS from this computer, or pair this device with "
                               "the link from `python -m app.auth token`.")
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
        print("New token written. Every paired device must pair again; restart is not needed.", file=sys.stderr)
        return 0
    print(__doc__)
    return 2


if __name__ == "__main__":
    sys.exit(_main(sys.argv[1:]))
