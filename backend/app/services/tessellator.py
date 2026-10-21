"""
Tessellation service — converts cadquery BREP shapes to triangle meshes.

Uses CadQuery's native Shape.tessellate(tolerance, angularTolerance) which
interfaces directly with OpenCASCADE's BRepMesh_IncrementalMesh and BRep_Tool.
Computes vertex normals via trimesh.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any, Optional, Tuple, List

import numpy as np

logger = logging.getLogger(__name__)


@dataclass
class MeshResult:
    """Triangulated mesh result."""
    vertices: list[float] = field(default_factory=list)   # flat: [x0, y0, z0, x1, y1, z1, ...]
    faces: list[int] = field(default_factory=list)        # flat: [i0, i1, i2, i3, i4, i5, ...]
    normals: list[float] = field(default_factory=list)    # flat: [nx0, ny0, nz0, ...]
    vertex_count: int = 0
    face_count: int = 0
    warning: str = ""

    @property
    def is_empty(self) -> bool:
        return self.vertex_count == 0


def tessellate_cadquery_shape(
    shape: Any,
    linear_deflection: float = 0.5,
    angular_deflection: float = 0.1,
) -> MeshResult:
    """
    Tessellate a cadquery Shape (Solid, Compound, or Workplane) using CadQuery's
    built-in tessellate() method.
    """
    result = MeshResult()
    try:
        # If passed a Workplane or object with .val(), unpack it
        cq_shape = shape.val() if hasattr(shape, "val") else shape

        if not hasattr(cq_shape, "tessellate"):
            result.warning = f"Object of type {type(cq_shape)} has no tessellate method"
            return result

        raw_verts, raw_tris = cq_shape.tessellate(linear_deflection, angular_deflection)
        if not raw_verts or not raw_tris:
            result.warning = "Tessellation returned empty vertices or triangles"
            return result

        # Flatten vertices
        verts_flat: list[float] = []
        for v in raw_verts:
            verts_flat.extend([float(v.x), float(v.y), float(v.z)])

        # Flatten faces
        faces_flat: list[int] = []
        for t in raw_tris:
            faces_flat.extend([int(t[0]), int(t[1]), int(t[2])])

        # Compute vertex normals via trimesh
        verts_np = np.array(verts_flat, dtype=np.float64).reshape(-1, 3)
        faces_np = np.array(faces_flat, dtype=np.int32).reshape(-1, 3)

        # Filter out degenerate faces
        valid = (
            (faces_np[:, 0] != faces_np[:, 1])
            & (faces_np[:, 1] != faces_np[:, 2])
            & (faces_np[:, 0] != faces_np[:, 2])
        )
        faces_np = faces_np[valid]

        if len(faces_np) == 0:
            result.warning = "All faces degenerate"
            return result

        try:
            import trimesh
            from trimesh import repair
            tm = trimesh.Trimesh(vertices=verts_np, faces=faces_np, process=True)
            repair.fix_normals(tm)
            result.vertices = tm.vertices.flatten().tolist()
            result.faces = tm.faces.flatten().tolist()
            result.normals = tm.vertex_normals.flatten().tolist()
            result.vertex_count = len(tm.vertices)
            result.face_count = len(tm.faces)
        except Exception as te:
            logger.warning(f"trimesh normal repair failed, falling back to raw geometry: {te}")
            result.vertices = verts_flat
            result.faces = faces_np.flatten().tolist()
            result.normals = [0.0] * len(verts_flat)
            result.vertex_count = len(raw_verts)
            result.face_count = len(faces_np)

        return result

    except Exception as e:
        logger.error(f"Tessellation error: {e}", exc_info=True)
        result.warning = str(e)
        return result
