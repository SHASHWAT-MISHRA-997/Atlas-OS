"""ATLAS OS API entry point: `uvicorn app.main:app` from the backend directory."""
import os
import sqlite3
from contextlib import asynccontextmanager
from pathlib import Path

import httpx  # noqa: F401 - tests patch ``app.main.httpx.AsyncClient`` to stub outbound calls
from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles

from . import auth, automations, devices, storage, task_engine
from .config import get_settings
from .providers import ProviderError, ollama_status
from .routers import automations as automations_router
from .routers import desktop, llm, memory, tasks
from .routers import devices as devices_router
from .routers import docs as docs_router
from .routers import voice as voice_router
from .security import BodySizeLimitMiddleware, SecurityHeadersMiddleware

VERSION = "0.14.0"

CANDIDATE_ROOT = Path(__file__).resolve().parents[2]
ROOT = CANDIDATE_ROOT if (CANDIDATE_ROOT / "frontend" / "index.html").exists() else Path(__file__).resolve().parents[1]
FRONTEND = ROOT / "frontend"


@asynccontextmanager
async def lifespan(_: FastAPI):
    if storage.server_storage_enabled():
        try:
            with storage.connection() as conn:
                storage.apply_retention(conn)
        except (storage.StorageError, OSError, sqlite3.Error):
            pass  # storage problems are reported by the routes that need it
    await task_engine.manager.start()
    await automations.scheduler.start()
    try:
        yield
    finally:
        await automations.scheduler.stop()
        await task_engine.manager.stop()


def create_app() -> FastAPI:
    settings = get_settings()
    docs = settings.enable_api_docs
    application = FastAPI(
        lifespan=lifespan,
        title="ATLAS OS API",
        version=VERSION,
        docs_url="/api/docs" if docs else None,
        redoc_url=None,
        openapi_url="/api/openapi.json" if docs else None,
    )
    # Same-origin by default. If frontend/backend are hosted separately, replace this
    # with a strict allowlist from environment configuration before production.
    application.add_middleware(
        CORSMiddleware,
        allow_origins=[],
        allow_credentials=False,
        allow_methods=["GET", "POST"],
        allow_headers=["Content-Type"],
    )
    application.add_middleware(BodySizeLimitMiddleware)
    application.add_middleware(auth.AuthMiddleware)
    application.add_middleware(SecurityHeadersMiddleware)

    @application.exception_handler(ProviderError)
    async def provider_error_handler(_: Request, exc: ProviderError):
        return JSONResponse(status_code=exc.status_code, content={"detail": exc.message, "code": exc.code})

    @application.exception_handler(storage.StorageError)
    async def storage_error_handler(_: Request, exc: storage.StorageError):
        return JSONResponse(status_code=exc.status_code, content={"detail": exc.message, "code": exc.code})

    @application.exception_handler(task_engine.TaskError)
    async def task_error_handler(_: Request, exc: task_engine.TaskError):
        return JSONResponse(status_code=exc.status_code, content={"detail": exc.message, "code": exc.code})

    @application.exception_handler(devices.DeviceError)
    async def device_error_handler(_: Request, exc: devices.DeviceError):
        return JSONResponse(status_code=exc.status_code, content={"detail": exc.message, "code": exc.code})

    @application.exception_handler(RequestValidationError)
    async def validation_error_handler(_: Request, exc: RequestValidationError):
        # Drop the offending input values: they can contain API keys or private prompt text.
        errors = [{"loc": list(e.get("loc", [])), "msg": e.get("msg", "invalid"), "type": e.get("type", "")}
                  for e in exc.errors()]
        summary = "; ".join(f"{'.'.join(str(p) for p in e['loc'][1:]) or 'body'}: {e['msg']}" for e in errors[:5])
        return JSONResponse(status_code=422, content={"detail": summary or "Invalid request.", "code": "validation_error",
                                                      "errors": errors})

    application.include_router(llm.router)
    application.include_router(desktop.router)
    application.include_router(tasks.router)
    application.include_router(memory.router)
    application.include_router(docs_router.router)
    application.include_router(voice_router.router)
    application.include_router(automations_router.router)
    application.include_router(devices_router.router)

    @application.get("/health")
    def health():
        return {"status": "ok", "service": "atlas-os-api", "version": VERSION, "mode": "local-first"}

    @application.get("/api/system/status")
    async def system_status():
        """Real status of each subsystem, for the UI's status panel."""
        current = get_settings()
        ollama = await ollama_status()
        return {
            "api": {"status": "ok", "version": VERSION, "env": current.env},
            "ollama": {"available": ollama["available"], "count": ollama.get("count", 0), "message": ollama["message"]},
            "external_providers_enabled": current.allow_external_providers,
            "desktop_agent_enabled": current.enable_desktop_agent,
            "task_runner": "background-engine" if task_engine.manager.started else "stopped",
            "auth": "token" if auth.auth_required() else "off",
            "memory_storage": "server-sqlite" if storage.server_storage_enabled() else "browser-local",
        }

    static_dir = FRONTEND / "static"
    if static_dir.is_dir():
        application.mount("/static", StaticFiles(directory=static_dir), name="static")

    @application.get("/sw.js", include_in_schema=False)
    def service_worker():
        # Served from the root so it may control "/". no-cache: a new version is picked up on the next visit.
        return FileResponse(FRONTEND / "static" / "sw.js", media_type="text/javascript",
                            headers={"Cache-Control": "no-cache"})

    @application.get("/", include_in_schema=False)
    def frontend(request: Request, pair: str | None = None):
        if pair is not None:
            # A one-time code from the Devices panel, or the install token from the CLI.
            name = devices.redeem_pairing_code(pair) or ("Paired with install token" if auth.token_matches(pair) else None)
            if name is None:
                return JSONResponse(status_code=401, content={"detail": "Pairing link is wrong, already used or expired.",
                                                              "code": "bad_pairing"})
            _, device_token = devices.register(name)
            # The device gets its own revocable token, never the install token. Redirect so the
            # code does not stay in the address bar or history.
            response = RedirectResponse("/", status_code=303)
            secure = request.url.scheme == "https" or request.headers.get("x-forwarded-proto") == "https" \
                or (os.getenv("ATLAS_PUBLIC_URL") or "").startswith("https://")
            response.headers["set-cookie"] = auth.session_cookie_header(device_token, secure=secure)
            return response
        response = FileResponse(FRONTEND / "index.html")
        if (auth.auth_required() and auth.is_same_computer(request.client.host if request.client else None, request.headers)
                and auth.identify(request.cookies.get(auth.COOKIE)) is None):
            # A browser on this machine is the owner, unless it already has a working session.
            response.headers["set-cookie"] = auth.session_cookie_header(auth.get_token())
        return response

    return application


app = create_app()
