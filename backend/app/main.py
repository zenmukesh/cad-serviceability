"""
FastAPI application entry point for the CAD Serviceability Assessment System.

Milestone 1: STEP import, component extraction, tessellation, 3D viewer data.
"""
import logging
import sys
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.config import settings
from app.database import init_db
from app.routers import upload, assembly, serviceability
from app.utils.version_info import collect_versions

# ─── Logging ──────────────────────────────────────────────────────────────────
logging.basicConfig(
    level=logging.DEBUG if settings.debug else logging.INFO,
    format="%(asctime)s | %(levelname)-8s | %(name)s | %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)],
)
logger = logging.getLogger(__name__)

# ─── App ───────────────────────────────────────────────────────────────────────
app = FastAPI(
    title=settings.app_name,
    version=settings.app_version,
    description=(
        "AI-Assisted CAD-Based Serviceability Assessment System. "
        "Milestone 1: STEP file import and 3D viewer backend."
    ),
    docs_url="/api/docs",
    redoc_url="/api/redoc",
    openapi_url="/api/openapi.json",
)

# ─── CORS ─────────────────────────────────────────────────────────────────────
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.allowed_origins_list,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ─── Routers ───────────────────────────────────────────────────────────────────
app.include_router(upload.router)
app.include_router(assembly.router)
app.include_router(serviceability.router)


# ─── Startup ──────────────────────────────────────────────────────────────────
@app.on_event("startup")
async def startup_event():
    logger.info(f"Starting {settings.app_name} v{settings.app_version}")
    # Ensure upload directory exists
    Path(settings.upload_dir).mkdir(parents=True, exist_ok=True)
    # Initialise database tables
    init_db()
    # Log dependency versions for traceability
    versions = collect_versions()
    logger.info(f"Software versions: {versions}")


# ─── Health check ─────────────────────────────────────────────────────────────
@app.get("/api/health", tags=["health"], summary="Health check and version info")
async def health():
    return {
        "status": "ok",
        "app": settings.app_name,
        "version": settings.app_version,
        "software_versions": collect_versions(),
    }


# ─── Global error handler ─────────────────────────────────────────────────────
@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception):
    logger.error(f"Unhandled exception on {request.url}: {exc}", exc_info=True)
    return JSONResponse(
        status_code=500,
        content={"detail": "An internal server error occurred.", "code": "internal_error"},
    )


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("app.main:app", host="0.0.0.0", port=8000, reload=True)
