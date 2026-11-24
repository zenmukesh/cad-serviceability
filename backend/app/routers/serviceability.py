"""
Serviceability Analysis Router.

Exposes endpoints for:
- Obstruction detection and multi-directional access paths
- Pairwise clearance measurements with 3D points
- Disassembly dependency DAG and removal sequence
- Explainable 0-100 Serviceability scoring and report
"""
from __future__ import annotations

import logging
from typing import List, Optional, Dict, Any

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.database import get_db
from app.models.assembly import Assembly, Component
from app.schemas.serviceability import (
    ClearanceMeasurement,
    ComponentObstructionReport,
    DisassemblyGraph,
    AssemblyServiceabilityReport,
    SectionPlaneRequest,
    AssemblySectionResponse,
)
from app.services.geometry_service import (
    analyze_clearances,
    analyze_component_obstructions,
    build_disassembly_graph,
    compute_serviceability_scoring,
)
from app.services.analysis_manager import (
    get_or_compute_analysis_bundle,
    get_cached_bundle,
    clear_analysis_cache,
)
from app.services.section_service import compute_assembly_section

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api", tags=["serviceability"])


class AnalyzeRequest(BaseModel):
    min_clearance_mm: Optional[float] = 3.0


@router.post(
    "/assemblies/{assembly_id}/analyze",
    response_model=AssemblyServiceabilityReport,
    summary="Run full serviceability analysis on an assembly",
)
async def run_serviceability_analysis(
    assembly_id: int,
    request: Optional[AnalyzeRequest] = None,
    db: Session = Depends(get_db),
):
    assembly = db.query(Assembly).filter(Assembly.id == assembly_id).first()
    if not assembly:
        raise HTTPException(status_code=404, detail=f"Assembly {assembly_id} not found")

    min_clearance = request.min_clearance_mm if (request and request.min_clearance_mm is not None) else 3.0

    try:
        bundle = await get_or_compute_analysis_bundle(assembly_id, db, min_clearance)
        return bundle.report
    except Exception as e:
        logger.exception(f"Error analyzing assembly {assembly_id}: {e}")
        raise HTTPException(status_code=500, detail="Geometric analysis failed during calculation. See server logs.")


@router.get(
    "/assemblies/{assembly_id}/serviceability",
    response_model=AssemblyServiceabilityReport,
    summary="Get serviceability report for an assembly",
)
async def get_serviceability_report(
    assembly_id: int,
    min_clearance_mm: float = Query(3.0, ge=0.1, le=100.0),
    db: Session = Depends(get_db),
):
    assembly = db.query(Assembly).filter(Assembly.id == assembly_id).first()
    if not assembly:
        raise HTTPException(status_code=404, detail=f"Assembly {assembly_id} not found")

    try:
        bundle = await get_or_compute_analysis_bundle(assembly_id, db, min_clearance_mm)
        return bundle.report
    except Exception as e:
        logger.exception(f"Error generating report for assembly {assembly_id}: {e}")
        raise HTTPException(status_code=500, detail="Failed to generate serviceability report. See server logs.")


@router.get(
    "/assemblies/{assembly_id}/components/{component_id}/obstructions",
    response_model=ComponentObstructionReport,
    summary="Get multi-directional obstruction analysis for a target component",
)
def get_component_obstructions(
    assembly_id: int,
    component_id: int,
    db: Session = Depends(get_db),
):
    comp = db.query(Component).filter(Component.id == component_id, Component.assembly_id == assembly_id).first()
    if not comp:
        raise HTTPException(status_code=404, detail=f"Component {component_id} not found in assembly {assembly_id}")

    assembly = db.query(Assembly).filter(Assembly.id == assembly_id).first()
    if assembly:
        cached = get_cached_bundle(assembly.sha256, 3.0)
        if cached and component_id in cached.obstructions:
            return cached.obstructions[component_id]

    try:
        return analyze_component_obstructions(assembly_id, component_id, db)
    except Exception as e:
        logger.exception(f"Error computing obstructions for component {component_id}: {e}")
        raise HTTPException(status_code=500, detail="Obstruction analysis failed. See server logs.")


@router.get(
    "/assemblies/{assembly_id}/components/{component_id}/clearances",
    response_model=List[ClearanceMeasurement],
    summary="Get clearance measurements from a target component to all neighbors",
)
def get_component_clearances(
    assembly_id: int,
    component_id: int,
    min_clearance_mm: float = Query(3.0, ge=0.1, le=100.0),
    db: Session = Depends(get_db),
):
    comp = db.query(Component).filter(Component.id == component_id, Component.assembly_id == assembly_id).first()
    if not comp:
        raise HTTPException(status_code=404, detail=f"Component {component_id} not found in assembly {assembly_id}")

    assembly = db.query(Assembly).filter(Assembly.id == assembly_id).first()
    if assembly:
        cached = get_cached_bundle(assembly.sha256, min_clearance_mm)
        if cached:
            return [
                c for c in cached.clearances
                if c.target_component_id == component_id or c.neighbor_component_id == component_id
            ]

    try:
        return analyze_clearances(
            assembly_id, db, target_component_id=component_id, min_threshold_mm=min_clearance_mm
        )
    except Exception as e:
        logger.exception(f"Error computing clearances for component {component_id}: {e}")
        raise HTTPException(status_code=500, detail="Clearance measurement failed. See server logs.")

@router.get(
    "/assemblies/{assembly_id}/clearances",
    response_model=List[ClearanceMeasurement],
    summary="Get all pairwise clearance measurements for an assembly",
)
def get_all_clearances(
    assembly_id: int,
    min_clearance_mm: float = Query(3.0, ge=0.1, le=100.0),
    db: Session = Depends(get_db),
):
    assembly = db.query(Assembly).filter(Assembly.id == assembly_id).first()
    if not assembly:
        raise HTTPException(status_code=404, detail=f"Assembly {assembly_id} not found")

    cached = get_cached_bundle(assembly.sha256, min_clearance_mm)
    if cached:
        return cached.clearances

    try:
        return analyze_clearances(assembly_id, db, min_threshold_mm=min_clearance_mm)
    except Exception as e:
        logger.exception(f"Error computing all clearances for assembly {assembly_id}: {e}")
        raise HTTPException(status_code=500, detail="Clearance calculations failed. See server logs.")

@router.get(
    "/assemblies/{assembly_id}/dependency-graph",
    response_model=DisassemblyGraph,
    summary="Get disassembly dependency graph and removal sequence",
)
def get_dependency_graph(
    assembly_id: int,
    db: Session = Depends(get_db),
):
    assembly = db.query(Assembly).filter(Assembly.id == assembly_id).first()
    if not assembly:
        raise HTTPException(status_code=404, detail=f"Assembly {assembly_id} not found")

    cached = get_cached_bundle(assembly.sha256, 3.0)
    if cached:
        return cached.graph

    try:
        return build_disassembly_graph(assembly_id, db)
    except Exception as e:
        logger.exception(f"Error building dependency graph for assembly {assembly_id}: {e}")
        raise HTTPException(status_code=500, detail="Dependency graph generation failed. See server logs.")

@router.post("/cache/clear", tags=["cache"], summary="Clear analysis cache")
def clear_cache():
    clear_analysis_cache()
    return {"status": "ok", "message": "Analysis cache cleared"}

@router.post(
    "/assemblies/{assembly_id}/section",
    response_model=AssemblySectionResponse,
    summary="Compute exact BREP multi-axis cross-section outlines, areas, and clearance",
)
def get_assembly_section(
    assembly_id: int,
    request: SectionPlaneRequest,
    db: Session = Depends(get_db),
):
    assembly = db.query(Assembly).filter(Assembly.id == assembly_id).first()
    if not assembly:
        raise HTTPException(status_code=404, detail=f"Assembly {assembly_id} not found")

    try:
        return compute_assembly_section(
            assembly_id=assembly_id,
            plane_point=request.point,
            plane_normal=request.normal,
            db=db,
            component_ids=request.component_ids,
            measure_clearance_between=request.measure_clearance_between,
        )
    except Exception as e:
        logger.exception(f"Error computing section for assembly {assembly_id}: {e}")
        raise HTTPException(status_code=500, detail="Section computation failed. See server logs.")

