"""
FastAPI application entry point for the CAD Serviceability Assessment System.

Production CAD Serviceability Assessment Engine:
- Multi-directional B-Rep ray casting & collision extraction
- Pairwise clearance & solid interference classification
- Disassembly sequence planning with motion path verification
- Explainable scoring & revision comparison
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
from app.utils.perf_tracker import get_call_counts
import time
from contextlib import asynccontextmanager
from datetime import datetime, timezone

# ─── Lifespan ─────────────────────────────────────────────────────────────────
@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info(f"Starting {settings.app_name} v{settings.app_version}")
    # Ensure upload directory exists
    Path(settings.upload_dir).mkdir(parents=True, exist_ok=True)
    # Initialise database tables
    init_db()
    # Log dependency versions for traceability
    versions = collect_versions()
    logger.info(f"Software versions: {versions}")
    # Pre-warm analysis process pool
    try:
        from app.services.analysis_manager import get_process_pool
        pool = get_process_pool()
        pool.submit(abs, 1)
    except Exception as e:
        logger.warning(f"Could not pre-warm process pool: {e}")
    yield
    try:
        from app.services.analysis_manager import shutdown_process_pool
        shutdown_process_pool()
    except Exception:
        pass


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
        "CAD-Native Geometric Serviceability Assessment Platform. "
        "Exact B-Rep clearances, interference volumes, tool approach, disassembly DAG, and explainable scoring."
    ),
    lifespan=lifespan,
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


# ─── Timing & Performance Middleware ──────────────────────────────────────────
@app.middleware("http")
async def timing_middleware(request: Request, call_next):
    t0 = time.perf_counter()
    start_counters = get_call_counts()
    ts_iso = datetime.now(timezone.utc).isoformat()

    response = await call_next(request)

    duration = time.perf_counter() - t0
    end_counters = get_call_counts()
    delta_counters = {
        k: end_counters[k] - start_counters.get(k, 0)
        for k in end_counters
        if end_counters[k] > start_counters.get(k, 0)
    }

    logger.info(
        f"[REQUEST_TIMING] timestamp={ts_iso} method={request.method} "
        f"endpoint={request.url.path} duration={duration:.4f}s "
        f"analysis_runs={delta_counters} total_cumulative={end_counters}"
    )
    response.headers["X-Process-Time"] = f"{duration:.4f}s"
    return response


# ─── Routers ───────────────────────────────────────────────────────────────────
app.include_router(upload.router)
app.include_router(assembly.router)
app.include_router(serviceability.router)


# ─── Health check ─────────────────────────────────────────────────────────────
@app.get("/api/health", tags=["health"], summary="Health check and version info")
async def health():
    from app.services.analysis_manager import get_cache_stats
    return {
        "status": "ok",
        "app": settings.app_name,
        "version": settings.app_version,
        "software_versions": collect_versions(),
        "cache_stats": get_cache_stats(),
    }


# ─── Global error handler ─────────────────────────────────────────────────────
@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception):
    logger.error(f"Unhandled exception on {request.url}: {exc}", exc_info=True)
    return JSONResponse(
        status_code=500,
        content={"detail": "An internal server error occurred.", "code": "INTERNAL_SERVER_ERROR", "message": "An internal server error occurred."},
    )


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("app.main:app", host="127.0.0.1", port=8000, reload=False)
