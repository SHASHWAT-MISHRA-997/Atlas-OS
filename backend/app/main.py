"""ATLAS OS API entry point: `uvicorn app.main:app` from the backend directory."""
from contextlib import asynccontextmanager
from pathlib import Path

import httpx  # noqa: F401 - tests patch ``app.main.httpx.AsyncClient`` to stub outbound calls
from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from . import storage, task_engine
from .config import get_settings
from .providers import ProviderError, ollama_status
from .routers import desktop, llm, memory, tasks
from .security import BodySizeLimitMiddleware, SecurityHeadersMiddleware

VERSION = "0.3.0"

CANDIDATE_ROOT = Path(__file__).resolve().parents[2]
ROOT = CANDIDATE_ROOT if (CANDIDATE_ROOT / "frontend" / "index.html").exists() else Path(__file__).resolve().parents[1]
FRONTEND = ROOT / "frontend"


@asynccontextmanager
async def lifespan(_: FastAPI):
    await task_engine.manager.start()
    try:
        yield
    finally:
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
            "memory_storage": "server-sqlite" if storage.server_storage_enabled() else "browser-local",
        }

    static_dir = FRONTEND / "static"
    if static_dir.is_dir():
        application.mount("/static", StaticFiles(directory=static_dir), name="static")

    @application.get("/", include_in_schema=False)
    def frontend():
        return FileResponse(FRONTEND / "index.html")

    return application


app = create_app()
