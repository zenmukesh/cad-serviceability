"""
Assembly router — query imported assemblies and their components.

GET  /api/assemblies              → list all assemblies
GET  /api/assemblies/{id}         → single assembly + component count
GET  /api/assemblies/{id}/components → full component tree
GET  /api/geometry/{component_id} → tessellated mesh JSON for viewer
PATCH /api/components/{id}/label  → update user-editable component label
"""
from __future__ import annotations

import json
import logging
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.database import get_db
from app.models.assembly import Assembly, Component
from app.schemas.assembly import (
    AssemblyRead,
    AssemblyWithComponents,
    BoundingBox,
    ComponentRead,
    ComponentLabelUpdate,
    MeshResponse,
    ComponentDelta,
    AssemblyComparisonResponse,
)

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api", tags=["assembly"])


def _component_to_schema(comp: Component) -> ComponentRead:
    return ComponentRead(
        id=comp.id,
        assembly_id=comp.assembly_id,
        cad_entity_id=comp.cad_entity_id,
        name=comp.name,
        user_label=comp.user_label or "",
        parent_cad_id=comp.parent_cad_id or "",
        depth=comp.depth or 0,
        is_leaf=bool(comp.is_leaf),
        component_type=comp.component_type or "solid",
        volume_mm3=comp.volume_mm3 or 0.0,
        surface_area_mm2=comp.surface_area_mm2 or 0.0,
        display_name=comp.display_name,
        bounding_box=BoundingBox(**comp.bounding_box),
    )


def _assembly_to_schema(assembly: Assembly, include_components: bool = False) -> dict[str, Any]:
    """Build a safe dict from ORM assembly (avoids lazy-load issues)."""
    d: dict[str, Any] = {
        "id": assembly.id,
        "filename": assembly.filename,
        "sha256": assembly.sha256,
        "revision_label": assembly.revision_label or "",
        "imported_at": assembly.imported_at,
        "status": assembly.status,
        "error_message": assembly.error_message or "",
        "importer_version": assembly.importer_version or "",
        "software_versions": assembly.get_software_versions(),
    }
    if include_components:
        d["components"] = [_component_to_schema(c) for c in assembly.components]
        d["component_count"] = len(assembly.components)
    else:
        d["component_count"] = len(assembly.components)
    return d


@router.get("/assemblies", summary="List all imported assemblies")
def list_assemblies(db: Session = Depends(get_db)) -> list[dict]:
    assemblies = db.query(Assembly).order_by(Assembly.imported_at.desc()).all()
    return [_assembly_to_schema(a) for a in assemblies]


@router.get("/assemblies/{assembly_id}", summary="Get assembly metadata and status")
def get_assembly(assembly_id: int, db: Session = Depends(get_db)) -> dict:
    assembly = db.query(Assembly).filter(Assembly.id == assembly_id).first()
    if not assembly:
        raise HTTPException(status_code=404, detail=f"Assembly {assembly_id} not found")
    return _assembly_to_schema(assembly, include_components=False)


@router.get(
    "/assemblies/{assembly_id}/components",
    summary="Get full component tree for an assembly",
)
def get_assembly_components(assembly_id: int, db: Session = Depends(get_db)) -> dict:
    assembly = db.query(Assembly).filter(Assembly.id == assembly_id).first()
    if not assembly:
        raise HTTPException(status_code=404, detail=f"Assembly {assembly_id} not found")

    if assembly.status == "processing":
        raise HTTPException(
            status_code=202,
            detail="Assembly is still being processed. Try again shortly.",
        )
    if assembly.status == "error":
        raise HTTPException(
            status_code=422,
            detail=f"Assembly import failed: {assembly.error_message}",
        )

    components = (
        db.query(Component)
        .filter(Component.assembly_id == assembly_id)
        .order_by(Component.depth, Component.id)
        .all()
    )

    return {
        "assembly_id": assembly_id,
        "filename": assembly.filename,
        "component_count": len(components),
        "components": [_component_to_schema(c) for c in components],
    }


@router.get(
    "/geometry/{component_id}",
    response_model=MeshResponse,
    summary="Get tessellated mesh for a component (for 3D viewer)",
)
def get_component_geometry(component_id: int, db: Session = Depends(get_db)) -> MeshResponse:
    comp = db.query(Component).filter(Component.id == component_id).first()
    if not comp:
        raise HTTPException(status_code=404, detail=f"Component {component_id} not found")

    if not comp.is_leaf or not comp.mesh_json:
        # Non-leaf containers or components without tessellatable geometry return empty mesh payload cleanly
        return MeshResponse(
            component_id=component_id,
            vertices=[],
            faces=[],
            normals=[],
            vertex_count=0,
            face_count=0,
        )

    try:
        mesh_data = json.loads(comp.mesh_json)
    except json.JSONDecodeError as e:
        raise HTTPException(status_code=500, detail=f"Mesh data is corrupted: {e}")

    return MeshResponse(
        component_id=component_id,
        vertices=mesh_data.get("vertices", []),
        faces=mesh_data.get("faces", []),
        normals=mesh_data.get("normals", []),
        vertex_count=mesh_data.get("vertex_count", 0),
        face_count=mesh_data.get("face_count", 0),
    )


@router.patch(
    "/components/{component_id}/label",
    summary="Update the user-editable label for a component",
)
def update_component_label(
    component_id: int,
    payload: ComponentLabelUpdate,
    db: Session = Depends(get_db),
) -> dict:
    comp = db.query(Component).filter(Component.id == component_id).first()
    if not comp:
        raise HTTPException(status_code=404, detail=f"Component {component_id} not found")

    comp.user_label = payload.user_label
    db.commit()
    db.refresh(comp)

    return {
        "component_id": comp.id,
        "user_label": comp.user_label,
        "display_name": comp.display_name,
    }


@router.delete(
    "/assemblies/{assembly_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Delete an assembly and all its components",
)
def delete_assembly(assembly_id: int, db: Session = Depends(get_db)):
    assembly = db.query(Assembly).filter(Assembly.id == assembly_id).first()
    if not assembly:
        raise HTTPException(status_code=404, detail=f"Assembly {assembly_id} not found")
    sha256 = assembly.sha256
    db.delete(assembly)
    db.commit()

    # Evict in-memory shape cache and any persistent analysis cache for this assembly
    try:
        from app.services.geometry_service import evict_shape_cache_for_assembly
        evict_shape_cache_for_assembly(assembly_id, sha256)
    except Exception as e:
        logger.warning(f"Could not evict shape cache on delete for assembly {assembly_id}: {e}")


@router.get(
    "/assemblies/{assembly_a_id}/compare/{assembly_b_id}",
    response_model=AssemblyComparisonResponse,
    summary="Compare two assemblies and calculate revision deltas",
)
def compare_assemblies(
    assembly_a_id: int,
    assembly_b_id: int,
    db: Session = Depends(get_db),
) -> AssemblyComparisonResponse:
    assembly_a = db.query(Assembly).filter(Assembly.id == assembly_a_id).first()
    if not assembly_a:
        raise HTTPException(status_code=404, detail=f"Assembly {assembly_a_id} not found")
    assembly_b = db.query(Assembly).filter(Assembly.id == assembly_b_id).first()
    if not assembly_b:
        raise HTTPException(status_code=404, detail=f"Assembly {assembly_b_id} not found")

    leaf_a = (
        db.query(Component)
        .filter(Component.assembly_id == assembly_a_id, Component.is_leaf == 1)
        .order_by(Component.name, Component.id)
        .all()
    )
    leaf_b = (
        db.query(Component)
        .filter(Component.assembly_id == assembly_b_id, Component.is_leaf == 1)
        .order_by(Component.name, Component.id)
        .all()
    )

    # Score lookup from cache if available
    from app.services.analysis_manager import get_cached_bundle
    bundle_a = get_cached_bundle(assembly_a.sha256, 1.0)
    bundle_b = get_cached_bundle(assembly_b.sha256, 1.0)
    score_a = round(bundle_a.report.overall_score, 1) if bundle_a and bundle_a.report else None
    score_b = round(bundle_b.report.overall_score, 1) if bundle_b and bundle_b.report else None
    score_delta = round(score_b - score_a, 1) if (score_a is not None and score_b is not None) else None

    # Track components by (name, occurrence)
    a_counts: dict[str, int] = {}
    a_map: dict[tuple[str, int], Component] = {}
    for c in leaf_a:
        cnt = a_counts.get(c.name, 0)
        a_map[(c.name, cnt)] = c
        a_counts[c.name] = cnt + 1

    b_counts: dict[str, int] = {}
    b_map: dict[tuple[str, int], Component] = {}
    for c in leaf_b:
        cnt = b_counts.get(c.name, 0)
        b_map[(c.name, cnt)] = c
        b_counts[c.name] = cnt + 1

    changes: list[ComponentDelta] = []
    matched_b_keys: set[tuple[str, int]] = set()

    for key, c_a in a_map.items():
        if key in b_map:
            matched_b_keys.add(key)
            c_b = b_map[key]
            vol_a = round(float(c_a.volume_mm3 or 0.0), 3)
            vol_b = round(float(c_b.volume_mm3 or 0.0), 3)
            vol_diff = round(vol_b - vol_a, 3)

            bb_a = c_a.bounding_box or {}
            bb_b = c_b.bounding_box or {}
            dx = round(abs((bb_b.get("x_max", 0) - bb_b.get("x_min", 0)) - (bb_a.get("x_max", 0) - bb_a.get("x_min", 0))), 3)
            dy = round(abs((bb_b.get("y_max", 0) - bb_b.get("y_min", 0)) - (bb_a.get("y_max", 0) - bb_a.get("y_min", 0))), 3)
            dz = round(abs((bb_b.get("z_max", 0) - bb_b.get("z_min", 0)) - (bb_a.get("z_max", 0) - bb_a.get("z_min", 0))), 3)

            is_modified = (abs(vol_diff) > 0.05) or (dx > 0.05 or dy > 0.05 or dz > 0.05)
            change_type = "modified" if is_modified else "unchanged"

            changes.append(
                ComponentDelta(
                    name=c_a.name,
                    cad_entity_id=c_a.cad_entity_id,
                    change_type=change_type,
                    volume_a_mm3=vol_a,
                    volume_b_mm3=vol_b,
                    volume_delta_mm3=vol_diff,
                    bb_delta={"dx": dx, "dy": dy, "dz": dz},
                )
            )
        else:
            vol_a = round(float(c_a.volume_mm3 or 0.0), 3)
            changes.append(
                ComponentDelta(
                    name=c_a.name,
                    cad_entity_id=c_a.cad_entity_id,
                    change_type="removed",
                    volume_a_mm3=vol_a,
                    volume_b_mm3=None,
                    volume_delta_mm3=-vol_a,
                    bb_delta=None,
                )
            )

    for key, c_b in b_map.items():
        if key not in matched_b_keys:
            vol_b = round(float(c_b.volume_mm3 or 0.0), 3)
            changes.append(
                ComponentDelta(
                    name=c_b.name,
                    cad_entity_id=c_b.cad_entity_id,
                    change_type="added",
                    volume_a_mm3=None,
                    volume_b_mm3=vol_b,
                    volume_delta_mm3=vol_b,
                    bb_delta=None,
                )
            )

    added_cnt = sum(1 for c in changes if c.change_type == "added")
    removed_cnt = sum(1 for c in changes if c.change_type == "removed")
    modified_cnt = sum(1 for c in changes if c.change_type == "modified")
    unchanged_cnt = sum(1 for c in changes if c.change_type == "unchanged")

    return AssemblyComparisonResponse(
        assembly_a_id=assembly_a_id,
        assembly_b_id=assembly_b_id,
        assembly_a_filename=assembly_a.filename,
        assembly_b_filename=assembly_b.filename,
        score_a=score_a,
        score_b=score_b,
        score_delta=score_delta,
        total_components_a=len(leaf_a),
        total_components_b=len(leaf_b),
        added_count=added_cnt,
        removed_count=removed_cnt,
        modified_count=modified_cnt,
        unchanged_count=unchanged_cnt,
        changes=changes,
    )
