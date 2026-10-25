"""HTTP hardening: security headers, request-size limits and a small rate limiter.

These are local-first defaults, not a substitute for a reverse proxy, TLS or
authentication in a hosted deployment (see docs/THREAT_MODEL.md).
"""
from __future__ import annotations

import json
import threading
import time
from collections import deque

from fastapi import HTTPException, Request

from .config import get_settings

# The app page uses only same-origin scripts. Inline style attributes are still
# used by the UI, so style-src keeps 'unsafe-inline'. Swagger UI loads assets
# from a CDN, so /api/docs is exempt from the CSP (it is off in production).
CSP = (
    "default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; "
    "img-src 'self' data: blob:; connect-src 'self'; media-src 'self' blob:; "
    "object-src 'none'; base-uri 'none'; frame-ancestors 'none'; form-action 'self'"
)
DOCS_PREFIXES = ("/api/docs", "/api/openapi.json", "/api/redoc")


class SecurityHeadersMiddleware:
    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            return await self.app(scope, receive, send)
        path = scope.get("path", "")

        async def send_with_headers(message):
            if message["type"] == "http.response.start":
                headers = list(message.get("headers", []))
                extra = {
                    b"x-content-type-options": b"nosniff",
                    b"referrer-policy": b"no-referrer",
                    b"x-frame-options": b"DENY",
                    b"cross-origin-opener-policy": b"same-origin",
                    # Microphone is same-origin only and still needs the browser's own prompt.
                    b"permissions-policy": b"camera=(), geolocation=(), microphone=(self)",
                }
                if not path.startswith(DOCS_PREFIXES):
                    extra[b"content-security-policy"] = CSP.encode()
                if path.startswith("/api/"):
                    extra[b"cache-control"] = b"no-store"
                present = {k.lower() for k, _ in headers}
                headers.extend((k, v) for k, v in extra.items() if k not in present)
                message["headers"] = headers
            await send(message)

        await self.app(scope, receive, send_with_headers)


# Endpoints that take recordings rather than JSON; they enforce the same cap themselves.
LARGER_BODY_LIMITS = {"/api/voice/transcribe": 10 * 1024 * 1024}


class BodySizeLimitMiddleware:
    """Reject request bodies larger than ATLAS_MAX_BODY_BYTES with HTTP 413."""

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            return await self.app(scope, receive, send)
        limit = LARGER_BODY_LIMITS.get(scope.get("path", ""), get_settings().max_body_bytes)
        for key, value in scope.get("headers", []):
            if key == b"content-length":
                try:
                    if int(value) > limit:
                        return await _send_413(send, limit)
                except ValueError:
                    return await _send_413(send, limit)
                return await self.app(scope, receive, send)
        if scope.get("method") in ("GET", "HEAD", "OPTIONS"):
            return await self.app(scope, receive, send)
        # No Content-Length (chunked): buffer up to the limit, then replay the body.
        chunks, received = [], 0
        while True:
            message = await receive()
            if message["type"] != "http.request":
                return await self.app(scope, receive, send)
            received += len(message.get("body", b""))
            if received > limit:
                return await _send_413(send, limit)
            chunks.append(message.get("body", b""))
            if not message.get("more_body", False):
                break
        replayed = False

        async def replay():
            nonlocal replayed
            if not replayed:
                replayed = True
                return {"type": "http.request", "body": b"".join(chunks), "more_body": False}
            return await receive()

        await self.app(scope, replay, send)


async def _send_413(send, limit: int):
    body = json.dumps({"detail": f"Request body exceeds the {limit} byte limit.", "code": "body_too_large"}).encode()
    await send({"type": "http.response.start", "status": 413,
                "headers": [(b"content-type", b"application/json"), (b"content-length", str(len(body)).encode())]})
    await send({"type": "http.response.body", "body": body})


class RateLimiter:
    """In-memory sliding window per client address. Single-process only."""

    def __init__(self):
        self._hits: dict[str, deque[float]] = {}
        self._lock = threading.Lock()

    def reset(self) -> None:
        with self._lock:
            self._hits.clear()

    def check(self, key: str, limit_per_minute: int) -> float | None:
        """Record a hit. Returns seconds to wait if the limit is exceeded, else None."""
        if limit_per_minute <= 0:
            return None
        now = time.monotonic()
        with self._lock:
            window = self._hits.setdefault(key, deque())
            while window and now - window[0] >= 60:
                window.popleft()
            if len(window) >= limit_per_minute:
                return max(0.0, 60 - (now - window[0]))
            window.append(now)
            if len(self._hits) > 10_000:
                # Bound memory: drop idle clients.
                for k in [k for k, v in self._hits.items() if not v]:
                    del self._hits[k]
        return None


llm_rate_limiter = RateLimiter()


def enforce_llm_rate_limit(request: Request) -> None:
    client = request.client.host if request.client else "unknown"
    wait = llm_rate_limiter.check(client, get_settings().llm_rate_limit_per_minute)
    if wait is not None:
        raise HTTPException(
            status_code=429,
            detail="ATLAS rate limit reached for model requests. Wait a moment and try again.",
            headers={"Retry-After": str(int(wait) + 1)},
        )
