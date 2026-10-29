"""
Analysis Manager with Single-Flight Concurrency and In-Memory Bundle Caching.

Ensures:
- Exactly one heavy CAD analysis execution per (assembly SHA-256, parameters).
- Concurrent identical requests share one in-flight computation (single-flight).
- Intermediate products (clearances, obstruction envelopes, disassembly DAG, scoring)
  are computed ONCE and bundled together.
- Scoring makes 0 calls to graph, clearances, or ray stages.
- Component clicks (/obstructions, /clearances) are served directly from the cached bundle in < 1 ms.
"""
from __future__ import annotations

import asyncio
import concurrent.futures
import logging
from dataclasses import dataclass
from typing import Dict, List, Optional, Tuple, Any

from sqlalchemy.orm import Session

from app.database import SessionLocal
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


@dataclass
class AnalysisBundle:
    report: AssemblyServiceabilityReport
    graph: DisassemblyGraph
    clearances: List[ClearanceMeasurement]
    obstructions: Dict[int, ComponentObstructionReport]


# In-memory bundle cache: (sha256, min_clearance_mm) -> AnalysisBundle
_BUNDLE_CACHE: Dict[Tuple[str, float], AnalysisBundle] = {}

# Single-flight tracking: key -> asyncio.Future
_IN_FLIGHT_FUTURES: Dict[Tuple[str, float], asyncio.Future] = {}
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


def get_cached_bundle(sha256: str, min_clearance_mm: float) -> Optional[AnalysisBundle]:
    """Retrieve precomputed bundle from memory cache if available."""
    key = (sha256, round(float(min_clearance_mm), 2))
    return _BUNDLE_CACHE.get(key)


def clear_analysis_cache() -> None:
    """Clear in-memory analysis cache."""
    _BUNDLE_CACHE.clear()


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
    Async entry point implementing Single-Flight lock and in-memory bundle caching.
    Guarantees concurrent requests for the same assembly share a single computation.
    """
    assembly = db.query(Assembly).filter(Assembly.id == assembly_id).first()
    if not assembly:
        raise ValueError(f"Assembly {assembly_id} not found")

    cache_key = (assembly.sha256, round(float(min_clearance_mm), 2))

    # Fast path: check memory cache
    if cache_key in _BUNDLE_CACHE:
        logger.info(f"Serving analysis bundle from in-memory cache for key {cache_key}")
        return _BUNDLE_CACHE[cache_key]

    # Single-flight coordination
    async with _FLIGHT_LOCK:
        if cache_key in _BUNDLE_CACHE:
            return _BUNDLE_CACHE[cache_key]

        if cache_key in _IN_FLIGHT_FUTURES:
            future = _IN_FLIGHT_FUTURES[cache_key]
            is_initiator = False
        else:
            loop = asyncio.get_running_loop()
            future = loop.create_future()
            _IN_FLIGHT_FUTURES[cache_key] = future
            is_initiator = True

    if not is_initiator:
        logger.info(f"Single-flight: joining existing in-flight analysis for key {cache_key}")
        return await future

    # Initiator runs the analysis in a separate process pool so the event loop never locks
    try:
        loop = asyncio.get_running_loop()
        pool = get_process_pool()
        bundle = await loop.run_in_executor(
            pool, _run_single_analysis_sync, assembly_id, min_clearance_mm
        )
        _BUNDLE_CACHE[cache_key] = bundle
        future.set_result(bundle)
        return bundle
    except Exception as e:
        logger.exception(f"Analysis failed for key {cache_key}: {e}")
        future.set_exception(e)
        raise
    finally:
        async with _FLIGHT_LOCK:
            _IN_FLIGHT_FUTURES.pop(cache_key, None)
