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
    db.delete(assembly)
    db.commit()
