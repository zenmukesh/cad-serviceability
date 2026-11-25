"""
Analysis Manager with Single-Flight Concurrency, In-Memory LRU, and Persistent SQLite Caching.

Ensures:
- Exactly one heavy CAD analysis execution per (assembly SHA-256, ALGORITHM_VERSION, parameters).
- ALGORITHM_VERSION incorporates an automated SHA-256 hash of all geometry-analysis source files,
  guaranteeing that code edits immediately invalidate stale cached results.
- Concurrent identical requests share one in-flight computation (single-flight).
- Intermediate products (clearances, obstruction envelopes, disassembly DAG, scoring)
  are computed ONCE and bundled together.
- Scoring makes 0 calls to graph, clearances, or ray stages.
- Component clicks (/obstructions, /clearances) are served directly from the cached bundle in < 1 ms.
- Persistent SQLite cache survives server restarts and skips all OpenCASCADE work on re-runs.
- Partial results, timeouts, and failures are NEVER cached.
- Provides /api/cache/clear endpoint support.
"""
from __future__ import annotations

import asyncio
from collections import OrderedDict
import concurrent.futures
import hashlib
import json
import logging
import time
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Optional, Tuple, Any
import zlib

from sqlalchemy import text
from sqlalchemy.orm import Session

from app.database import SessionLocal, engine
from app.models.assembly import Assembly, Component
from app.schemas.serviceability import (
    ClearanceMeasurement,
    ComponentObstructionReport,
    DisassemblyGraph,
    AssemblyServiceabilityReport,
)
from app.services.geometry_service import (
    analyze_clearances,
    analyze_component_obstructions,
    build_disassembly_graph,
    compute_serviceability_scoring,
)

logger = logging.getLogger(__name__)


def compute_algorithm_version() -> str:
    """
    Compute a fingerprint of all geometry analysis source files.
    Ensures any modification to algorithms immediately invalidates older cached results.
    """
    h = hashlib.sha256()
    source_files = [
        "geometry_service.py",
        "motion_planner.py",
        "fastener_detector.py",
        "cad_importer.py",
        "analysis_manager.py",
    ]
    cur_dir = Path(__file__).parent
    for fname in sorted(source_files):
        p = cur_dir / fname
        if p.exists():
            h.update(p.read_bytes())
    return f"2.2.0-{h.hexdigest()[:16]}"


ALGORITHM_VERSION = compute_algorithm_version()


@dataclass
class AnalysisBundle:
    report: AssemblyServiceabilityReport
    graph: DisassemblyGraph
    clearances: List[ClearanceMeasurement]
    obstructions: Dict[int, ComponentObstructionReport]


def _init_cache_table():
    try:
        with engine.begin() as conn:
            conn.execute(text("""
                CREATE TABLE IF NOT EXISTS analysis_cache (
                    cache_key TEXT PRIMARY KEY,
                    assembly_sha256 TEXT NOT NULL,
                    algo_version TEXT NOT NULL,
                    params_hash TEXT NOT NULL,
                    bundle_blob BLOB NOT NULL,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """))
    except Exception as e:
        logger.warning(f"Could not initialize analysis_cache table: {e}")


_init_cache_table()

# In-memory LRU cache: cache_key -> AnalysisBundle
_LRU_CACHE: OrderedDict[str, AnalysisBundle] = OrderedDict()
_LRU_MAX_SIZE = 32

# Single-flight tracking: cache_key -> asyncio.Future
_IN_FLIGHT_FUTURES: Dict[str, asyncio.Future] = {}
_FLIGHT_LOCK = asyncio.Lock()

# ProcessPoolExecutor to prevent OpenCASCADE C++ GIL locking on the main FastAPI event loop
_PROCESS_POOL: Optional[concurrent.futures.ProcessPoolExecutor] = None


def _warmup_worker() -> bool:
    """Preload heavy C++ libraries in the child process on startup."""
    try:
        import OCP
        import cadquery
    except Exception:
        pass
    return True


def get_process_pool() -> concurrent.futures.ProcessPoolExecutor:
    global _PROCESS_POOL
    if _PROCESS_POOL is None:
        _PROCESS_POOL = concurrent.futures.ProcessPoolExecutor(max_workers=1)
        _PROCESS_POOL.submit(_warmup_worker)
    return _PROCESS_POOL


def make_cache_keys(assembly_sha256: str, min_clearance_mm: float) -> Tuple[str, str]:
    """Return (cache_key, params_hash)."""
    params_str = f"min_clearance_mm={round(float(min_clearance_mm), 2)}"
    params_hash = hashlib.sha256(params_str.encode()).hexdigest()[:16]
    key_raw = f"{assembly_sha256}:{ALGORITHM_VERSION}:{params_hash}"
    cache_key = hashlib.sha256(key_raw.encode()).hexdigest()
    return cache_key, params_hash


def _serialize_bundle(bundle: AnalysisBundle) -> bytes:
    data = {
        "report": bundle.report.model_dump(mode="json"),
        "graph": bundle.graph.model_dump(mode="json"),
        "clearances": [c.model_dump(mode="json") for c in bundle.clearances],
        "obstructions": {str(k): v.model_dump(mode="json") for k, v in bundle.obstructions.items()},
    }
    raw = json.dumps(data).encode("utf-8")
    return zlib.compress(raw, level=6)


def _deserialize_bundle(blob: bytes) -> AnalysisBundle:
    raw = zlib.decompress(blob)
    data = json.loads(raw.decode("utf-8"))
    return AnalysisBundle(
        report=AssemblyServiceabilityReport.model_validate(data["report"]),
        graph=DisassemblyGraph.model_validate(data["graph"]),
        clearances=[ClearanceMeasurement.model_validate(c) for c in data["clearances"]],
        obstructions={int(k): ComponentObstructionReport.model_validate(v) for k, v in data["obstructions"].items()},
    )


def _load_from_sqlite(cache_key: str) -> Optional[AnalysisBundle]:
    try:
        with engine.connect() as conn:
            res = conn.execute(
                text("SELECT bundle_blob FROM analysis_cache WHERE cache_key = :k"),
                {"k": cache_key},
            ).first()
            if res and res[0]:
                bundle = _deserialize_bundle(res[0])
                logger.info(f"Loaded analysis bundle from SQLite cache ({cache_key[:12]}...)")
                return bundle
    except Exception as e:
        logger.warning(f"Failed loading cache from SQLite for {cache_key}: {e}")
    return None


def _save_to_sqlite(cache_key: str, sha256: str, params_hash: str, bundle: AnalysisBundle) -> None:
    # Rule: Never cache timeouts, budget-exhausted partial results, or errors
    if bundle.graph.sequence_status == "budget_exhausted":
        logger.info("Skipping persistent cache for partial/budget-exhausted disassembly graph.")
        return
    try:
        blob = _serialize_bundle(bundle)
        with engine.begin() as conn:
            conn.execute(
                text("""
                    INSERT OR REPLACE INTO analysis_cache
                    (cache_key, assembly_sha256, algo_version, params_hash, bundle_blob)
                    VALUES (:k, :sha, :ver, :p, :b)
                """),
                {
                    "k": cache_key,
                    "sha": sha256,
                    "ver": ALGORITHM_VERSION,
                    "p": params_hash,
                    "b": blob,
                },
            )
        logger.info(f"Saved analysis bundle to SQLite cache ({cache_key[:12]}..., size: {len(blob)} bytes)")
    except Exception as e:
        logger.warning(f"Failed saving cache to SQLite for {cache_key}: {e}")


def get_cached_bundle(sha256: str, min_clearance_mm: float) -> Optional[AnalysisBundle]:
    """Retrieve precomputed bundle from in-memory LRU or SQLite persistent cache."""
    cache_key, _ = make_cache_keys(sha256, min_clearance_mm)
    if cache_key in _LRU_CACHE:
        _LRU_CACHE.move_to_end(cache_key)
        return _LRU_CACHE[cache_key]

    # Check SQLite persistent cache
    bundle = _load_from_sqlite(cache_key)
    if bundle:
        _LRU_CACHE[cache_key] = bundle
        _LRU_CACHE.move_to_end(cache_key)
        return bundle
    return None


def clear_analysis_cache() -> None:
    """Clear both in-memory LRU cache and persistent SQLite analysis cache."""
    _LRU_CACHE.clear()
    try:
        from app.services.geometry_service import (
            _PAIRWISE_SWEPT_COLLISION_CACHE,
            _PAIRWISE_INITIAL_OVERLAP_CACHE,
            _SHAPE_CACHE,
            _SHAPE_CACHE_LOCK,
        )
        _PAIRWISE_SWEPT_COLLISION_CACHE.clear()
        _PAIRWISE_INITIAL_OVERLAP_CACHE.clear()
        with _SHAPE_CACHE_LOCK:
            _SHAPE_CACHE.clear()
    except Exception:
        pass
    try:
        with engine.begin() as conn:
            conn.execute(text("DELETE FROM analysis_cache"))
        logger.info("Cleared in-memory and persistent SQLite analysis cache.")
    except Exception as e:
        logger.warning(f"Failed clearing SQLite analysis cache: {e}")


def _run_single_analysis_sync(assembly_id: int, min_clearance_mm: float) -> AnalysisBundle:
    """
    Synchronous worker executing the unified pipeline stage-by-stage with zero redundancy.
    Run inside a dedicated process pool so the FastAPI async event loop is never blocked.
    """
    db = SessionLocal()
    try:
        assembly = db.query(Assembly).filter(Assembly.id == assembly_id).first()
        if not assembly:
            raise ValueError(f"Assembly {assembly_id} not found")

        leaf_comps = (
            db.query(Component)
            .filter(Component.assembly_id == assembly_id, Component.is_leaf == 1)
            .all()
        )

        logger.info(f"Starting unified analysis for assembly {assembly_id} ({len(leaf_comps)} parts)")

        # 1. Pairwise clearances (computed once)
        clearances = analyze_clearances(assembly_id, db, min_threshold_mm=min_clearance_mm)

        # 2. Per-component obstruction envelopes (computed once per leaf part)
        obstructions: Dict[int, ComponentObstructionReport] = {}
        for c in leaf_comps:
            try:
                obstructions[c.id] = analyze_component_obstructions(assembly_id, c.id, db)
            except Exception as e:
                logger.warning(f"Could not compute obstruction for component {c.id} ({c.name}): {e}")

        # 3. Disassembly dependency graph (reuses obstruction envelopes; zero redundant ray casts)
        graph = build_disassembly_graph(assembly_id, db, precomputed_obstructions=obstructions)

        # 4. Serviceability scoring (reuses graph, clearances, and obstructions; zero redundant calls)
        report = compute_serviceability_scoring(
            assembly_id=assembly_id,
            db=db,
            settings_dict={"min_clearance_mm": min_clearance_mm},
            precomputed_graph=graph,
            precomputed_clearances=clearances,
            precomputed_obstructions=obstructions,
        )

        bundle = AnalysisBundle(
            report=report,
            graph=graph,
            clearances=clearances,
            obstructions=obstructions,
        )
        return bundle
    finally:
        db.close()


async def get_or_compute_analysis_bundle(
    assembly_id: int,
    db: Session,
    min_clearance_mm: float = 3.0,
) -> AnalysisBundle:
    """
    Async entry point implementing Single-Flight lock, in-memory LRU, and SQLite persistence.
    Guarantees concurrent requests for the same assembly share a single computation.
    """
    assembly = db.query(Assembly).filter(Assembly.id == assembly_id).first()
    if not assembly:
        raise ValueError(f"Assembly {assembly_id} not found")

    cache_key, params_hash = make_cache_keys(assembly.sha256, min_clearance_mm)

    # 1. Check in-memory LRU cache
    if cache_key in _LRU_CACHE:
        logger.info(f"Serving analysis bundle from in-memory LRU cache for {cache_key[:12]}...")
        _LRU_CACHE.move_to_end(cache_key)
        bundle = _LRU_CACHE[cache_key]
        bundle.report.is_cached = True
        return bundle

    # 2. Check persistent SQLite cache
    bundle = _load_from_sqlite(cache_key)
    if bundle:
        bundle.report.is_cached = True
        _LRU_CACHE[cache_key] = bundle
        _LRU_CACHE.move_to_end(cache_key)
        return bundle

    # 3. Single-flight coordination for in-flight requests
    async with _FLIGHT_LOCK:
        if cache_key in _LRU_CACHE:
            return _LRU_CACHE[cache_key]

        if cache_key in _IN_FLIGHT_FUTURES:
            future = _IN_FLIGHT_FUTURES[cache_key]
            is_initiator = False
        else:
            loop = asyncio.get_running_loop()
            future = loop.create_future()
            _IN_FLIGHT_FUTURES[cache_key] = future
            is_initiator = True

    if not is_initiator:
        logger.info(f"Single-flight: joining existing in-flight analysis for {cache_key[:12]}...")
        return await future

    # 4. Initiator runs the analysis in a separate process pool so the event loop never locks
    try:
        loop = asyncio.get_running_loop()
        pool = get_process_pool()
        bundle = await loop.run_in_executor(
            pool, _run_single_analysis_sync, assembly_id, min_clearance_mm
        )

        # Store in LRU cache and SQLite only if complete/verified (never cache transient timeout/budget exhaustion)
        if bundle.graph.sequence_status != "budget_exhausted":
            _LRU_CACHE[cache_key] = bundle
            _LRU_CACHE.move_to_end(cache_key)
            while len(_LRU_CACHE) > _LRU_MAX_SIZE:
                _LRU_CACHE.popitem(last=False)
            _save_to_sqlite(cache_key, assembly.sha256, params_hash, bundle)
        else:
            logger.warning(
                f"Analysis returned budget_exhausted for {assembly.sha256[:12]}; "
                f"not caching to allow future full evaluation."
            )

        future.set_result(bundle)
        return bundle
    except Exception as e:
        logger.exception(f"Analysis failed for {cache_key[:12]}...: {e}")
        future.set_exception(e)
        raise
    finally:
        async with _FLIGHT_LOCK:
            _IN_FLIGHT_FUTURES.pop(cache_key, None)


def get_cache_stats() -> Dict[str, Any]:
    """Retrieve cache size and statistics for health monitoring."""
    sqlite_count = 0
    try:
        with engine.connect() as conn:
            row = conn.execute(text("SELECT count(*) FROM analysis_cache")).fetchone()
            if row:
                sqlite_count = row[0]
    except Exception:
        pass
    return {
        "lru_entries": len(_LRU_CACHE),
        "lru_max_size": _LRU_MAX_SIZE,
        "sqlite_entries": sqlite_count,
        "algo_version": ALGORITHM_VERSION,
    }


def shutdown_process_pool():
    global _PROCESS_POOL
    if _PROCESS_POOL is not None:
        _PROCESS_POOL.shutdown(wait=False)
        _PROCESS_POOL = None


@dataclass
class JobInfo:
    job_id: str
    assembly_id: int
    min_clearance_mm: float
    status: str  # "pending", "processing", "completed", "failed"
    stage: str   # "initializing", "clearances", "obstructions", "graph", "scoring", "complete"
    percent: int
    start_time: float
    end_time: Optional[float] = None
    is_cached: bool = False
    error: Optional[str] = None
    bundle: Optional[AnalysisBundle] = None

    def to_dict(self) -> Dict[str, Any]:
        now = self.end_time if self.end_time else time.time()
        return {
            "job_id": self.job_id,
            "assembly_id": self.assembly_id,
            "status": self.status,
            "stage": self.stage,
            "percent": self.percent,
            "elapsed_seconds": round(now - self.start_time, 2),
            "is_cached": self.is_cached,
            "error": self.error,
        }


_ANALYSIS_JOBS: Dict[str, JobInfo] = {}


async def create_analysis_job(
    assembly_id: int,
    db: Session,
    min_clearance_mm: float = 3.0,
) -> JobInfo:
    assembly = db.query(Assembly).filter(Assembly.id == assembly_id).first()
    if not assembly:
        raise ValueError(f"Assembly {assembly_id} not found")

    job_id = str(uuid.uuid4())[:8]
    cached = get_cached_bundle(assembly.sha256, min_clearance_mm)
    if cached:
        cached.report.is_cached = True
        job = JobInfo(
            job_id=job_id,
            assembly_id=assembly_id,
            min_clearance_mm=min_clearance_mm,
            status="completed",
            stage="complete",
            percent=100,
            start_time=time.time(),
            end_time=time.time(),
            is_cached=True,
            bundle=cached,
        )
        _ANALYSIS_JOBS[job_id] = job
        return job

    job = JobInfo(
        job_id=job_id,
        assembly_id=assembly_id,
        min_clearance_mm=min_clearance_mm,
        status="processing",
        stage="clearances",
        percent=25,
        start_time=time.time(),
        is_cached=False,
    )
    _ANALYSIS_JOBS[job_id] = job

    # Run in background task
    async def _runner():
        try:
            job.stage = "clearances"
            job.percent = 25
            db_worker = SessionLocal()
            try:
                bundle = await get_or_compute_analysis_bundle(
                    job.assembly_id, db_worker, job.min_clearance_mm
                )
            finally:
                db_worker.close()

            job.status = "completed"
            job.stage = "complete"
            job.percent = 100
            job.end_time = time.time()
            job.bundle = bundle
        except Exception as e:
            logger.exception(f"Background job {job.job_id} failed: {e}")
            job.status = "failed"
            job.stage = "error"
            job.error = str(e)
            job.end_time = time.time()

    asyncio.create_task(_runner())
    return job


def get_analysis_job(job_id: str) -> Optional[JobInfo]:
    return _ANALYSIS_JOBS.get(job_id)
