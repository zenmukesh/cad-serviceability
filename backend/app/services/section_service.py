"""
Exact Multi-Axis Sectioning Service (Phase D).

Performs exact analytical cross-section cuts of CAD components using OpenCASCADE:
- BRepAlgoAPI_Section for exact 3D boundary outline edges/curves
- BRepAlgoAPI_Common with planar face for exact cross-section face area (via GProp_GProps)
- BRepExtrema_DistShapeShape for exact section-plane clearance between cut outlines
"""
from __future__ import annotations

import logging
import math
from typing import List, Optional, Tuple, Dict, Any

from sqlalchemy.orm import Session

from app.models.assembly import Assembly, Component
from app.schemas.serviceability import (
    AssemblySectionResponse,
    ComponentSectionOutline,
    SectionClearanceResult,
)
from app.services.geometry_service import get_assembly_shapes

logger = logging.getLogger(__name__)

# Cache for section evaluations: (assembly_id, plane_p_tuple, plane_n_tuple, comp_ids_tuple) -> AssemblySectionResponse
_SECTION_CACHE: Dict[Tuple, AssemblySectionResponse] = {}


def _discretize_section_shape(sec_shape: Any, deflection: float = 0.1) -> List[List[List[float]]]:
    """
    Extract and discretize boundary edges of a section into polyline point sequences.
    """
    from OCP.TopExp import TopExp_Explorer
    from OCP.TopAbs import TopAbs_EDGE
    from OCP.BRepAdaptor import BRepAdaptor_Curve
    from OCP.GCPnts import GCPnts_UniformDeflection
    from OCP.TopoDS import TopoDS

    polylines: List[List[List[float]]] = []
    exp = TopExp_Explorer(sec_shape, TopAbs_EDGE)
    while exp.More():
        edge = TopoDS.Edge_s(exp.Current())
        curve = BRepAdaptor_Curve(edge)
        discr = GCPnts_UniformDeflection(curve, deflection)
        if discr.IsDone() and discr.NbPoints() > 1:
            pts: List[List[float]] = []
            for i in range(1, discr.NbPoints() + 1):
                p = discr.Value(i)
                pts.append([round(p.X(), 4), round(p.Y(), 4), round(p.Z(), 4)])
            polylines.append(pts)
        exp.Next()
    return polylines


def cut_solid_with_plane(
    occ_shape: Any,
    plane_point: List[float],
    plane_normal: List[float],
    deflection: float = 0.1,
) -> Tuple[float, List[List[List[float]]], Any]:
    """
    Cut an OpenCASCADE solid shape with an arbitrary plane.
    Returns:
        (area_mm2, polylines, section_shape)
    """
    from OCP.BRepAlgoAPI import BRepAlgoAPI_Section, BRepAlgoAPI_Common
    from OCP.BRepBuilderAPI import BRepBuilderAPI_MakeFace
    from OCP.gp import gp_Pln, gp_Pnt, gp_Dir
    from OCP.GProp import GProp_GProps
    from OCP.BRepGProp import BRepGProp
    from OCP.Bnd import Bnd_Box
    from OCP.BRepBndLib import BRepBndLib

    # Normalize plane normal
    nx, ny, nz = plane_normal
    n_mag = math.sqrt(nx * nx + ny * ny + nz * nz)
    if n_mag < 1e-9:
        nx, ny, nz = 0.0, 0.0, 1.0
    else:
        nx, ny, nz = nx / n_mag, ny / n_mag, nz / n_mag

    px, py, pz = plane_point

    # Check bounding box first
    bbox = Bnd_Box()
    BRepBndLib.Add_s(occ_shape, bbox)
    if bbox.IsVoid():
        return 0.0, [], None

    xmin, ymin, zmin, xmax, ymax, zmax = bbox.Get()
    corners = [
        (xmin, ymin, zmin), (xmax, ymin, zmin), (xmin, ymax, zmin), (xmax, ymax, zmin),
        (xmin, ymin, zmax), (xmax, ymin, zmax), (xmin, ymax, zmax), (xmax, ymax, zmax),
    ]

    # Broadphase test: distances of all corners to plane
    dists = [(cx - px) * nx + (cy - py) * ny + (cz - pz) * nz for cx, cy, cz in corners]
    if min(dists) > 1e-4 or max(dists) < -1e-4:
        # Solid does not intersect plane at all
        return 0.0, [], None

    # Exact section edges
    pln = gp_Pln(gp_Pnt(px, py, pz), gp_Dir(nx, ny, nz))
    sec = BRepAlgoAPI_Section(occ_shape, pln, False)
    sec.Build()
    if not sec.IsDone():
        return 0.0, [], None

    sec_shape = sec.Shape()
    polylines = _discretize_section_shape(sec_shape, deflection=deflection)
    if not polylines:
        return 0.0, [], sec_shape

    # Exact planar cut face area via BRepAlgoAPI_Common
    # Compute centroid of bounding box and project onto cutting plane
    cx = (xmin + xmax) * 0.5
    cy = (ymin + ymax) * 0.5
    cz = (zmin + zmax) * 0.5
    c_dist = (cx - px) * nx + (cy - py) * ny + (cz - pz) * nz
    proj_x = cx - c_dist * nx
    proj_y = cy - c_dist * ny
    proj_z = cz - c_dist * nz

    # Extent large enough to cover the bounding box
    dx = xmax - xmin
    dy = ymax - ymin
    dz = zmax - zmin
    r_diag = math.sqrt(dx * dx + dy * dy + dz * dz) * 0.75 + 10.0

    pln_proj = gp_Pln(gp_Pnt(proj_x, proj_y, proj_z), gp_Dir(nx, ny, nz))
    cut_face = BRepBuilderAPI_MakeFace(pln_proj, -r_diag, r_diag, -r_diag, r_diag).Face()

    common = BRepAlgoAPI_Common(occ_shape, cut_face)
    common.Build()

    area_mm2 = 0.0
    if common.IsDone():
        props = GProp_GProps()
        BRepGProp.SurfaceProperties_s(common.Shape(), props)
        area_mm2 = max(0.0, round(props.Mass(), 4))

    return area_mm2, polylines, sec_shape


def measure_section_clearance(
    sec_shape_a: Any,
    sec_shape_b: Any,
    comp_a: Component,
    comp_b: Component,
) -> Optional[SectionClearanceResult]:
    """
    Compute minimum Euclidean distance between the cut outlines of two components
    on the section plane using BRepExtrema_DistShapeShape.
    """
    if sec_shape_a is None or sec_shape_b is None:
        return None

    from OCP.BRepExtrema import BRepExtrema_DistShapeShape

    dss = BRepExtrema_DistShapeShape(sec_shape_a, sec_shape_b)
    dss.Perform()

    if not dss.IsDone() or dss.NbSolution() == 0:
        return None

    min_dist = float(dss.Value())
    p1 = dss.PointOnShape1(1)
    p2 = dss.PointOnShape2(1)

    return SectionClearanceResult(
        component_a_id=comp_a.id,
        component_b_id=comp_b.id,
        component_a_name=comp_a.display_name,
        component_b_name=comp_b.display_name,
        clearance_mm=round(min_dist, 4),
        point_a=[round(p1.X(), 4), round(p1.Y(), 4), round(p1.Z(), 4)],
        point_b=[round(p2.X(), 4), round(p2.Y(), 4), round(p2.Z(), 4)],
    )


def compute_assembly_section(
    assembly_id: int,
    plane_point: List[float],
    plane_normal: List[float],
    db: Session,
    component_ids: Optional[List[int]] = None,
    measure_clearance_between: Optional[List[int]] = None,
) -> AssemblySectionResponse:
    """
    Cut assembly solids with the given plane and return outlines, areas, and section clearance.
    """
    # Normalize plane normal
    nx, ny, nz = plane_normal
    mag = math.sqrt(nx * nx + ny * ny + nz * nz)
    if mag < 1e-9:
        nx, ny, nz = 0.0, 0.0, 1.0
    else:
        nx, ny, nz = nx / mag, ny / mag, nz / mag
    normalized_normal = [nx, ny, nz]

    cache_key = (
        assembly_id,
        tuple(round(p, 4) for p in plane_point),
        tuple(round(n, 4) for n in normalized_normal),
        tuple(sorted(component_ids)) if component_ids else None,
        tuple(sorted(measure_clearance_between)) if measure_clearance_between else None,
    )
    if cache_key in _SECTION_CACHE:
        return _SECTION_CACHE[cache_key]

    assembly = db.query(Assembly).filter(Assembly.id == assembly_id).first()
    if not assembly:
        raise ValueError(f"Assembly {assembly_id} not found")

    leaf_comps = (
        db.query(Component)
        .filter(Component.assembly_id == assembly_id, Component.is_leaf == True)
        .all()
    )

    if component_ids:
        filter_set = set(component_ids)
        leaf_comps = [c for c in leaf_comps if c.id in filter_set]

    shapes_dict = get_assembly_shapes(assembly_id, db)

    sections: List[ComponentSectionOutline] = []
    sec_shapes_by_id: Dict[int, Any] = {}
    total_area = 0.0

    for comp in leaf_comps:
        cad_shape = shapes_dict.get(comp.cad_entity_id)
        if not cad_shape:
            continue

        occ_solid = getattr(cad_shape, "wrapped", cad_shape)
        area, outlines, sec_shape = cut_solid_with_plane(
            occ_solid, plane_point, normalized_normal, deflection=0.1
        )

        if outlines and area > 1e-6:
            sections.append(
                ComponentSectionOutline(
                    component_id=comp.id,
                    component_name=comp.display_name,
                    area_mm2=area,
                    outlines=outlines,
                )
            )
            sec_shapes_by_id[comp.id] = sec_shape
            total_area += area

    clearance_result: Optional[SectionClearanceResult] = None

    if measure_clearance_between and len(measure_clearance_between) == 2:
        id_a, id_b = measure_clearance_between
        comp_a = next((c for c in leaf_comps if c.id == id_a), None)
        comp_b = next((c for c in leaf_comps if c.id == id_b), None)
        if comp_a and comp_b and id_a in sec_shapes_by_id and id_b in sec_shapes_by_id:
            clearance_result = measure_section_clearance(
                sec_shapes_by_id[id_a], sec_shapes_by_id[id_b], comp_a, comp_b
            )
    elif len(sections) >= 2:
        # Automatically find closest pair among cut components
        best_dist = float("inf")
        best_clearance: Optional[SectionClearanceResult] = None
        for i in range(len(sections)):
            for j in range(i + 1, len(sections)):
                id_i = sections[i].component_id
                id_j = sections[j].component_id
                c_i = next(c for c in leaf_comps if c.id == id_i)
                c_j = next(c for c in leaf_comps if c.id == id_j)
                clr = measure_section_clearance(
                    sec_shapes_by_id[id_i], sec_shapes_by_id[id_j], c_i, c_j
                )
                if clr and clr.clearance_mm < best_dist:
                    best_dist = clr.clearance_mm
                    best_clearance = clr
        clearance_result = best_clearance

    response = AssemblySectionResponse(
        assembly_id=assembly_id,
        plane_point=plane_point,
        plane_normal=normalized_normal,
        total_cut_area_mm2=round(total_area, 4),
        component_sections=sections,
        clearance=clearance_result,
    )

    _SECTION_CACHE[cache_key] = response
    return response
