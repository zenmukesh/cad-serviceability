"""Pydantic schemas for Assembly and Component API I/O."""
from __future__ import annotations

from datetime import datetime
from typing import Any, Optional

from pydantic import BaseModel, Field


# ─── Component Schemas ──────────────────────────────────────────────────────

class BoundingBox(BaseModel):
    xmin: float
    xmax: float
    ymin: float
    ymax: float
    zmin: float
    zmax: float
    size_x: float
    size_y: float
    size_z: float


class ComponentBase(BaseModel):
    name: str = ""
    user_label: str = ""
    cad_entity_id: str = ""
    parent_cad_id: str = ""
    depth: int = 0
    is_leaf: bool = True
    component_type: str = "solid"


class ComponentCreate(ComponentBase):
    assembly_id: int
    bb_xmin: float = 0.0
    bb_xmax: float = 0.0
    bb_ymin: float = 0.0
    bb_ymax: float = 0.0
    bb_zmin: float = 0.0
    bb_zmax: float = 0.0
    volume_mm3: float = 0.0
    surface_area_mm2: float = 0.0
    placement_matrix: str = ""
    mesh_json: str = ""


class ComponentRead(ComponentBase):
    id: int
    assembly_id: int
    volume_mm3: float
    surface_area_mm2: float
    bounding_box: BoundingBox
    display_name: str

    model_config = {"from_attributes": True}


class ComponentLabelUpdate(BaseModel):
    user_label: str = Field(..., min_length=1, max_length=512)


class MeshResponse(BaseModel):
    """Tessellated mesh for browser rendering."""
    component_id: int
    vertices: list[float]   # flat array: [x0,y0,z0, x1,y1,z1, ...]
    faces: list[int]        # flat array: [i0,i1,i2, i3,i4,i5, ...]
    normals: list[float]    # flat array, per-vertex
    vertex_count: int
    face_count: int


# ─── Assembly Schemas ────────────────────────────────────────────────────────

class AssemblyRead(BaseModel):
    id: int
    filename: str
    sha256: str
    revision_label: str
    imported_at: datetime
    status: str
    error_message: str
    importer_version: str
    component_count: Optional[int] = None
    software_versions: Optional[dict[str, Any]] = None

    model_config = {"from_attributes": True}


class AssemblyWithComponents(AssemblyRead):
    components: list[ComponentRead] = []


class UploadResponse(BaseModel):
    assembly_id: int
    filename: str
    sha256: str
    status: str
    message: str


class ErrorResponse(BaseModel):
    detail: str
    code: str = "error"
