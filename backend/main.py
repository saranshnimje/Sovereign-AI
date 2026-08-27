"""
Sovereign AI Workbench — FastAPI application factory.
All middleware, routers, and lifespan hooks are registered here.
"""
import logging
import uuid
from contextlib import asynccontextmanager

import structlog
from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware

from config import get_settings
from database import init_db
from routers import auth, chat, models, system, audit, providers, settings as settings_router

# ------------------------------------------------------------------
# Logging setup
# ------------------------------------------------------------------
logging.basicConfig(level=logging.INFO)
logger = structlog.get_logger()


# ------------------------------------------------------------------
# Lifespan: startup / shutdown
# ------------------------------------------------------------------
@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = get_settings()
    logger.info("Starting Sovereign AI Workbench", ollama=settings.ollama_url, qdrant=settings.qdrant_url)

    # Ensure data directories exist (derived from settings.data_dir)
    import os
    from pathlib import Path
    data_dir = Path(settings.data_dir)
    for sub in ["sqlite", "uploads", "sandbox_workspace"]:
        (data_dir / sub).mkdir(parents=True, exist_ok=True)

    await init_db()
    logger.info("Database initialised")

    # Seed the default Ollama provider entry if none exist
    from database import AsyncSessionLocal
    from services.provider_service import ProviderService
    async with AsyncSessionLocal() as seed_db:
        svc = ProviderService(seed_db)
        await svc.seed_default_ollama(settings.ollama_url)
        await seed_db.commit()
    yield
    logger.info("Shutdown complete")


# ------------------------------------------------------------------
# App factory
# ------------------------------------------------------------------
def create_app() -> FastAPI:
    settings = get_settings()

    app = FastAPI(
        title="Sovereign AI Workbench API",
        version="1.0.0",
        docs_url="/api/docs",
        redoc_url="/api/redoc",
        openapi_url="/api/openapi.json",
        lifespan=lifespan,
    )

    # ---- CORS ----
    app.add_middleware(
        CORSMiddleware,
        allow_origins=[settings.frontend_origin, "http://localhost:5173", "http://localhost"],
        allow_credentials=True,
        allow_methods=["GET", "POST", "PUT", "DELETE", "PATCH", "OPTIONS"],
        allow_headers=["Authorization", "Content-Type", "X-Request-ID"],
    )

    # ---- Request ID middleware ----
    class RequestIDMiddleware(BaseHTTPMiddleware):
        async def dispatch(self, request: Request, call_next):
            request_id = request.headers.get("X-Request-ID", str(uuid.uuid4()))
            request.state.request_id = request_id
            response = await call_next(request)
            response.headers["X-Request-ID"] = request_id
            return response

    app.add_middleware(RequestIDMiddleware)

    # ---- Security headers ----
    class SecurityHeadersMiddleware(BaseHTTPMiddleware):
        async def dispatch(self, request: Request, call_next):
            response = await call_next(request)
            response.headers["X-Content-Type-Options"] = "nosniff"
            response.headers["X-Frame-Options"] = "DENY"
            response.headers["X-XSS-Protection"] = "1; mode=block"
            response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
            return response

    app.add_middleware(SecurityHeadersMiddleware)

    # ---- Routers ----
    prefix = "/api/v1"
    app.include_router(auth.router,            prefix=f"{prefix}/auth")
    app.include_router(chat.router,            prefix=f"{prefix}/chat")
    app.include_router(models.router,          prefix=f"{prefix}/models")
    app.include_router(system.router,          prefix=f"{prefix}/system")
    app.include_router(audit.router,           prefix=f"{prefix}/audit")
    app.include_router(settings_router.router, prefix=f"{prefix}/settings")
    app.include_router(providers.router,       prefix=f"{prefix}/models/providers")

    # ---- Exception handlers ----
    @app.exception_handler(RequestValidationError)
    async def validation_error_handler(request: Request, exc: RequestValidationError):
        # Pydantic v2 puts a raw Exception object in error['ctx']['error'] which
        # is not JSON-serialisable. Strip it down to string form.
        def _clean(errors: list) -> list:
            cleaned = []
            for e in errors:
                entry = {k: v for k, v in e.items() if k != "ctx"}
                if "ctx" in e:
                    ctx = {k: str(v) for k, v in e["ctx"].items()}
                    entry["ctx"] = ctx
                # loc is a tuple — make it a list for JSON
                if "loc" in entry:
                    entry["loc"] = list(entry["loc"])
                cleaned.append(entry)
            return cleaned

        return JSONResponse(
            status_code=422,
            content={
                "error": {
                    "code": "validation_error",
                    "message": "Input validation failed",
                    "details": _clean(exc.errors()),
                    "trace_id": getattr(request.state, "request_id", None),
                }
            },
        )

    @app.exception_handler(Exception)
    async def global_error_handler(request: Request, exc: Exception):
        trace_id = getattr(request.state, "request_id", "unknown")
        logger.exception("Unhandled error", trace_id=trace_id, error=str(exc))
        return JSONResponse(
            status_code=500,
            content={
                "error": {
                    "code": "internal_error",
                    "message": "An unexpected error occurred.",
                    "trace_id": trace_id,
                }
            },
        )

    return app


app = create_app()
