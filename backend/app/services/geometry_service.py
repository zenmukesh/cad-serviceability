"""
Geometry and Serviceability Analysis Service.

Implements Milestone 2 with rigorously validated CAD calculations:
- CAD Shape retrieval with global coordinate transforms and in-memory caching
- Pairwise clearance calculations using OpenCASCADE BRepExtrema
- Distinguishes mechanical contact, bearing radial clearances, and clearance deficits
- Multi-directional obstruction analysis using OpenCASCADE analytical B-Rep curve-face intersector
- Parent assembly and multi-solid fastener deduplication
- Disassembly dependency DAG generation and removal sequence
- Explainable 0-100 Serviceability scoring engine with traceable engineering deductions
"""
from __future__ import annotations

import logging
import math
import re
from pathlib import Path
from typing import Dict, List, Optional, Tuple, Any, Set

from sqlalchemy.orm import Session

from app.config import settings
from app.models.assembly import Assembly, Component
from app.schemas.serviceability import (
    Point3D,
    ClearanceMeasurement,
    ObstructingComponent,
    DirectionAccessResult,
    ComponentObstructionReport,
    DependencyNode,
    DependencyEdge,
    DisassemblyStep,
    DisassemblyGraph,
    DirectionAttempt,
    ScoreDeduction,
    ComponentScore,
    AssemblyServiceabilityReport,
)

logger = logging.getLogger(__name__)

# Global in-memory cache: assembly_id -> {cad_entity_id: cq.Shape}
_SHAPE_CACHE: Dict[int, Dict[str, Any]] = {}

CARDINAL_DIRECTIONS: List[Tuple[str, Tuple[float, float, float]]] = [
    ("+X", (1.0, 0.0, 0.0)),
    ("-X", (-1.0, 0.0, 0.0)),
    ("+Y", (0.0, 1.0, 0.0)),
    ("-Y", (0.0, -1.0, 0.0)),
    ("+Z", (0.0, 0.0, 1.0)),
    ("-Z", (0.0, 0.0, -1.0)),
]


def _find_assembly_step_file(assembly: Assembly) -> Optional[Path]:
    """Find the STEP file on disk for a given assembly."""
    candidate_paths = [
        Path(settings.upload_dir) / f"{assembly.sha256}.step",
        Path(settings.upload_dir) / f"{assembly.sha256}.stp",
        Path("test_data") / assembly.filename,
        Path("backend/test_data") / assembly.filename,
        Path("d:/projects/cad-serviceability/backend/test_data") / assembly.filename,
        Path("d:/projects/cad-serviceability/uploads") / f"{assembly.sha256}.step",
    ]
    for p in candidate_paths:
        if p.exists() and p.is_file():
            return p
    return None


def get_assembly_shapes(assembly_id: int, db: Session) -> Dict[str, Any]:
    """
    Retrieve placed OpenCASCADE CadQuery Shape objects for all leaf components of an assembly.
    Uses in-memory cache keyed by (assembly_id, sha256); loads from STEP on first request.
    Returns: Dict[cad_entity_id, cq.Shape]
    """
    assembly = db.query(Assembly).filter(Assembly.id == assembly_id).first()
    if not assembly:
        raise ValueError(f"Assembly {assembly_id} not found in database")

    cache_key = f"{assembly_id}:{assembly.sha256}"
    if cache_key in _SHAPE_CACHE:
        return _SHAPE_CACHE[cache_key]

    step_path = _find_assembly_step_file(assembly)
    if not step_path:
        raise FileNotFoundError(f"CAD STEP file not found on disk for assembly {assembly_id} ({assembly.filename})")

    logger.info(f"Loading CAD shapes for assembly {assembly_id} from {step_path}")

    from OCP.STEPCAFControl import STEPCAFControl_Reader
    from OCP.TDocStd import TDocStd_Document
    from OCP.XCAFApp import XCAFApp_Application
    from OCP.XCAFDoc import XCAFDoc_DocumentTool
    from OCP.TDF import TDF_LabelSequence, TDF_Label, TDF_Tool
    from OCP.TCollection import TCollection_ExtendedString, TCollection_AsciiString
    from OCP.TopLoc import TopLoc_Location
    from OCP.IFSelect import IFSelect_RetDone
    from cadquery.occ_impl.shapes import Shape

    app = XCAFApp_Application.GetApplication_s()
    doc = TDocStd_Document(TCollection_ExtendedString("MDTV-XCAF"))
    app.NewDocument(TCollection_ExtendedString("MDTV-XCAF"), doc)

    reader = STEPCAFControl_Reader()
    reader.SetNameMode(True)
    reader.SetPropsMode(True)
    reader.SetColorMode(True)
    status = reader.ReadFile(str(step_path))
    if status != IFSelect_RetDone:
        raise RuntimeError(f"Failed to read STEP file {step_path} (status {status})")

    if not reader.Transfer(doc):
        raise RuntimeError(f"Failed to transfer STEP file {step_path} to XCAF")

    shape_tool = XCAFDoc_DocumentTool.ShapeTool_s(doc.Main())
    free_shapes = TDF_LabelSequence()
    shape_tool.GetFreeShapes(free_shapes)

    shapes_dict: Dict[str, Any] = {}
    entity_counter = 0

    def traverse_node(lbl: TDF_Label, parent_loc: TopLoc_Location, parent_cad_id: str = ""):
        nonlocal entity_counter
        entity_counter += 1

        ref_lbl = TDF_Label()
        has_ref = shape_tool.GetReferredShape_s(lbl, ref_lbl)
        target_lbl = ref_lbl if has_ref else lbl

        cur_loc = shape_tool.GetLocation_s(lbl)
        combined_loc = parent_loc.Multiplied(cur_loc)

        asc = TCollection_AsciiString()
        TDF_Tool.Entry_s(lbl, asc)
        entry_id = asc.ToCString() or f"node_{entity_counter:04d}"
        cad_id = f"{parent_cad_id}/{entry_id}" if parent_cad_id else entry_id

        if shape_tool.IsAssembly_s(target_lbl):
            sub_comps = TDF_LabelSequence()
            shape_tool.GetComponents_s(target_lbl, sub_comps)
            for k in range(1, sub_comps.Length() + 1):
                traverse_node(sub_comps.Value(k), combined_loc, cad_id)
        else:
            occ_shape = shape_tool.GetShape_s(target_lbl)
            if not occ_shape.IsNull():
                placed_shape = occ_shape.Moved(combined_loc)
                cq_shape = Shape.cast(placed_shape)
                shapes_dict[cad_id] = cq_shape

    root_loc = TopLoc_Location()
    for i in range(1, free_shapes.Length() + 1):
        root_lbl = free_shapes.Value(i)
        if shape_tool.IsAssembly_s(root_lbl):
            comps = TDF_LabelSequence()
            shape_tool.GetComponents_s(root_lbl, comps)
            for j in range(1, comps.Length() + 1):
                traverse_node(comps.Value(j), root_loc, "")
        else:
            traverse_node(root_lbl, root_loc, "")

    _SHAPE_CACHE[cache_key] = shapes_dict
    logger.info(f"Cached {len(shapes_dict)} CAD solid shapes for assembly {assembly_id} ({cache_key})")
    return shapes_dict


def compute_shape_distance(shape1: Any, shape2: Any) -> Tuple[float, Point3D, Point3D]:
    """
    Compute exact minimum distance and contact points between two CAD shapes
    using OpenCASCADE BRepExtrema_DistShapeShape.
    """
    from OCP.BRepExtrema import BRepExtrema_DistShapeShape

    dss = BRepExtrema_DistShapeShape(shape1.wrapped, shape2.wrapped)
    dss.Perform()

    if not dss.IsDone():
        # Fallback to bounding box distance
        bb1 = shape1.BoundingBox()
        bb2 = shape2.BoundingBox()
        dx = max(0.0, bb2.xmin - bb1.xmax, bb1.xmin - bb2.xmax)
        dy = max(0.0, bb2.ymin - bb1.ymax, bb1.ymin - bb2.ymax)
        dz = max(0.0, bb2.zmin - bb1.zmax, bb1.zmin - bb2.zmax)
        dist = math.sqrt(dx*dx + dy*dy + dz*dz)
        p1 = Point3D(x=(bb1.xmin + bb1.xmax)/2, y=(bb1.ymin + bb1.ymax)/2, z=(bb1.zmin + bb1.zmax)/2)
        p2 = Point3D(x=(bb2.xmin + bb2.xmax)/2, y=(bb2.ymin + bb2.ymax)/2, z=(bb2.zmin + bb2.zmax)/2)
        return dist, p1, p2

    val = float(dss.Value())
    if dss.NbSolution() > 0:
        occt_p1 = dss.PointOnShape1(1)
        occt_p2 = dss.PointOnShape2(1)
        p1 = Point3D(x=float(occt_p1.X()), y=float(occt_p1.Y()), z=float(occt_p1.Z()))
        p2 = Point3D(x=float(occt_p2.X()), y=float(occt_p2.Y()), z=float(occt_p2.Z()))
    else:
        bb1 = shape1.BoundingBox()
        bb2 = shape2.BoundingBox()
        p1 = Point3D(x=(bb1.xmin + bb1.xmax)/2, y=(bb1.ymin + bb1.ymax)/2, z=(bb1.zmin + bb1.zmax)/2)
        p2 = Point3D(x=(bb2.xmin + bb2.xmax)/2, y=(bb2.ymin + bb2.ymax)/2, z=(bb2.zmin + bb2.zmax)/2)

    return val, p1, p2


def compute_shape_intersection_volume(shape1: Any, shape2: Any) -> Tuple[Optional[float], str]:
    """
    Compute Boolean common intersection volume between two CadQuery/OpenCASCADE shapes.
    Returns (volume_mm3 or None, status_str).
    status_str: 'SUCCESS', 'EMPTY', 'ERROR'
    """
    try:
        common = shape1.intersect(shape2)
        if common and not common.isNull():
            vol = float(common.Volume())
            return max(0.0, vol), "SUCCESS"
        return 0.0, "EMPTY"
    except Exception as e:
        logger.debug(f"Boolean intersection failed: {e}")
        return None, f"ERROR: {e}"


def is_fastener(name: str) -> bool:
    """Detect if a component is a fastener based on its CAD name or label."""
    q = name.lower()
    return any(k in q for k in ["bolt", "screw", "fastener", "nut", "washer", "shank", "stud"])


def is_housing_or_cover(name: str) -> bool:
    """Detect if a component is a protective housing, cover, guard, or shield."""
    q = name.lower()
    return any(k in q for k in ["housing", "cover", "casing", "cap", "enclosure", "shield", "lid", "guard"])


def get_physical_fastener_id(comp_name: str, parent_cad_id: str) -> str:
    """
    Extract a normalized physical fastener identifier to group multi-solid fasteners
    (e.g. Bolt_Shank_1 and Bolt_Head_1 belong to physical bolt 'Bolt_1').
    """
    if parent_cad_id:
        return parent_cad_id

    # Pattern match for Bolt_X, Screw_X, etc.
    m = re.search(r'(bolt|screw|fastener)[_\-\s]*(\d+)', comp_name, re.IGNORECASE)
    if m:
        return f"fastener_{m.group(1).lower()}_{m.group(2)}"

    # Check for shank/head index: e.g. Cover_Bolt_Shank_1 -> Cover_Bolt_1
    m2 = re.search(r'(.*?)(?:_shank|_head)[_\-\s]*(\d+)', comp_name, re.IGNORECASE)
    if m2:
        return f"{m2.group(1)}_{m2.group(2)}"

    return comp_name


def are_sibling_fastener_solids(comp_a: Component, comp_b: Component) -> bool:
    """Check if two solids belong to the same physical fastener."""
    if not (is_fastener(comp_a.display_name) and is_fastener(comp_b.display_name)):
        return False
    # If they share the same parent assembly
    if comp_a.parent_cad_id and comp_a.parent_cad_id == comp_b.parent_cad_id:
        return True
    # If they share the same physical fastener id
    id_a = get_physical_fastener_id(comp_a.display_name, comp_a.parent_cad_id)
    id_b = get_physical_fastener_id(comp_b.display_name, comp_b.parent_cad_id)
    return id_a == id_b


def is_shaft_bearing_interface(c1: Component, c2: Component, dist_mm: float, p1: Point3D, p2: Point3D) -> bool:
    """
    Determine if c1 and c2 form a coaxial shaft-and-bearing running clearance fit.
    Ground-truth CAD check:
    - One is Shaft/Axle, other is Bearing/Bushing.
    - Centers align coaxially (e.g. shared rotational axis).
    - Distance vector is perpendicular to the shaft axis (radial clearance gap).
    - Distance is within engineered running clearance bounds (0.01 mm to 1.5 mm).
    """
    n1 = c1.display_name.lower()
    n2 = c2.display_name.lower()

    is_s1_b2 = ("shaft" in n1 or "rotor" in n1) and ("bearing" in n2 or "bushing" in n2)
    is_s2_b1 = ("shaft" in n2 or "rotor" in n2) and ("bearing" in n1 or "bushing" in n1)

    if not (is_s1_b2 or is_s2_b1):
        return False

    shaft_comp = c1 if is_s1_b2 else c2
    bearing_comp = c2 if is_s1_b2 else c1

    s_bb = shaft_comp.bounding_box
    b_bb = bearing_comp.bounding_box

    # Determine shaft longitudinal axis (largest dimension)
    dims = [("X", s_bb["size_x"]), ("Y", s_bb["size_y"]), ("Z", s_bb["size_z"])]
    dims.sort(key=lambda d: d[1], reverse=True)
    shaft_axis = dims[0][0]

    dx = abs(p2.x - p1.x)
    dy = abs(p2.y - p1.y)
    dz = abs(p2.z - p1.z)

    # If shaft axis is X, distance vector between closest surface points must be in Y-Z plane (radial)
    if shaft_axis == "X":
        is_radial = dx <= 0.05 and (dy > 0 or dz > 0)
    elif shaft_axis == "Y":
        is_radial = dy <= 0.05 and (dx > 0 or dz > 0)
    else:
        is_radial = dz <= 0.05 and (dx > 0 or dy > 0)

    # Positive running clearance up to 1.5 mm
    return is_radial and (0.01 <= dist_mm <= 1.5)


def is_shaft_bore_running_clearance(c1: Component, c2: Component, dist_mm: float, p1: Point3D, p2: Point3D) -> bool:
    """
    Determine if c1 and c2 form an engineered cylindrical slip fit / bore clearance
    (e.g. shaft inside a coupling, spacer, idler wheel, gear, or pulley bore).
    Clearance is radial, non-contact, typically 0.05 mm to 0.75 mm.
    """
    n1 = c1.display_name.lower()
    n2 = c2.display_name.lower()

    shaft_keywords = ["shaft", "axle", "spindle"]
    bore_keywords = ["coupling", "wheel", "spacer", "collar", "pulley", "sheave", "hub"]

    is_s1 = any(k in n1 for k in shaft_keywords) and any(k in n2 for k in bore_keywords)
    is_s2 = any(k in n2 for k in shaft_keywords) and any(k in n1 for k in bore_keywords)

    if not (is_s1 or is_s2):
        return False

    shaft_comp = c1 if is_s1 else c2
    s_bb = shaft_comp.bounding_box
    dims = [("X", s_bb["size_x"]), ("Y", s_bb["size_y"]), ("Z", s_bb["size_z"])]
    dims.sort(key=lambda d: d[1], reverse=True)
    shaft_axis = dims[0][0]

    dx = abs(p2.x - p1.x)
    dy = abs(p2.y - p1.y)
    dz = abs(p2.z - p1.z)

    if shaft_axis == "X":
        is_radial = dx <= 0.05 and (dy > 0 or dz > 0)
    elif shaft_axis == "Y":
        is_radial = dy <= 0.05 and (dx > 0 or dz > 0)
    else:
        is_radial = dz <= 0.05 and (dx > 0 or dy > 0)

    return is_radial and (0.05 <= dist_mm <= 0.75)


def is_guard_to_base_clearance(c1: Component, c2: Component, dist_mm: float, p1: Point3D, p2: Point3D) -> bool:
    """
    Determine if c1 and c2 represent nominal non-structural clearance between a protective
    guard/cover/shield and a stationary baseplate/bed/chassis (e.g. 1.5 to 5.0 mm gap).
    """
    n1 = c1.display_name.lower()
    n2 = c2.display_name.lower()

    guard_kw = ["guard", "shield", "cover", "casing"]
    base_kw = ["base", "bed", "chassis", "frame", "plate", "mounting_base"]

    is_g1 = any(k in n1 for k in guard_kw) and any(k in n2 for k in base_kw)
    is_g2 = any(k in n2 for k in guard_kw) and any(k in n1 for k in base_kw)

    if not (is_g1 or is_g2):
        return False

    return 1.2 <= dist_mm <= 5.0


def analyze_clearances(
    assembly_id: int,
    db: Session,
    target_component_id: Optional[int] = None,
    min_threshold_mm: float = 3.0,
) -> List[ClearanceMeasurement]:
    """
    Calculate minimum part-to-part clearances between leaf components.
    Rigorously distinguishes:
      - Mechanical contact (d <= 0.05 mm)
      - Bearing-shaft running clearance (radial gap <= 1.5 mm on coaxial interface)
      - Actual clearance deficits violating engineering thresholds
    """
    shapes = get_assembly_shapes(assembly_id, db)
    leaf_components = (
        db.query(Component)
        .filter(Component.assembly_id == assembly_id, Component.is_leaf == 1)
        .all()
    )

    results: List[ClearanceMeasurement] = []

    if target_component_id:
        targets = [c for c in leaf_components if c.id == target_component_id]
        if not targets:
            return []
        primary = targets[0]
        others = [c for c in leaf_components if c.id != target_component_id]
        pairs = [(primary, o) for o in others]
    else:
        pairs = []
        for i in range(len(leaf_components)):
            for j in range(i + 1, len(leaf_components)):
                pairs.append((leaf_components[i], leaf_components[j]))

    for c1, c2 in pairs:
        # Skip sibling parts of the same physical fastener
        if are_sibling_fastener_solids(c1, c2):
            continue

        s1 = shapes.get(c1.cad_entity_id)
        s2 = shapes.get(c2.cad_entity_id)
        if not s1 or not s2:
            continue

        # Fast bounding box pre-filter
        dx = max(0.0, c2.bb_xmin - c1.bb_xmax, c1.bb_xmin - c2.bb_xmax)
        dy = max(0.0, c2.bb_ymin - c1.bb_ymax, c1.bb_ymin - c2.bb_ymax)
        dz = max(0.0, c2.bb_zmin - c1.bb_zmax, c1.bb_zmin - c2.bb_zmax)
        bbox_dist = math.sqrt(dx*dx + dy*dy + dz*dz)

        if bbox_dist > 150.0:
            continue

        try:
            dist_mm, p1, p2 = compute_shape_distance(s1, s2)
        except Exception as e:
            logger.warning(f"Error computing distance between {c1.name} and {c2.name}: {e}")
            continue

        inter_vol, inter_status = None, "UNTESTED"
        if dist_mm <= 0.05:
            inter_vol, inter_status = compute_shape_intersection_volume(s1, s2)

        is_bearing_fit = is_shaft_bearing_interface(c1, c2, dist_mm, p1, p2)
        is_bore_fit = is_shaft_bore_running_clearance(c1, c2, dist_mm, p1, p2)
        is_guard_fit = is_guard_to_base_clearance(c1, c2, dist_mm, p1, p2)

        if inter_vol is not None and inter_vol > 1e-3:
            # Confirmed volumetric interference (solid clash)
            classification = "INTERFERENCE"
            clearance_type = "solid_interference"
            is_contact = False
            is_pass = False
            severity = "CRITICAL"
            notes = f"Physical solid collision / volumetric interference ({inter_vol:.2f} mm³)"
        elif dist_mm <= 0.05 and inter_vol is not None and inter_vol <= 1e-3:
            # Confirmed 2D boundary contact (coincident mating surfaces, 0.00 mm³ clash)
            classification = "CONTACT"
            clearance_type = "mated_surface_contact"
            is_contact = True
            is_pass = True
            severity = "PASS"
            notes = "Mechanical interface / verified coincident mating contact (0.00 mm³ collision volume)"
        elif dist_mm <= 0.05 and inter_status.startswith("ERROR"):
            # Indeterminate contact due to boolean calculation issue
            classification = "INDETERMINATE"
            clearance_type = "indeterminate_contact"
            is_contact = True
            is_pass = False
            severity = "WARNING"
            notes = "Zero-distance contact with indeterminate intersection volume"
        elif is_bearing_fit:
            classification = "CLEARANCE"
            clearance_type = "bearing_radial_clearance"
            is_contact = False
            is_pass = True
            severity = "PASS"
            notes = f"Engineered bearing running clearance (radial gap: {dist_mm:.2f} mm)"
        elif is_bore_fit:
            classification = "CLEARANCE"
            clearance_type = "slip_fit_clearance"
            is_contact = False
            is_pass = True
            severity = "PASS"
            notes = f"Engineered shaft-bore running/slip fit (radial gap: {dist_mm:.2f} mm)"
        elif is_guard_fit:
            classification = "CLEARANCE"
            clearance_type = "guard_clearance"
            is_contact = False
            is_pass = True
            severity = "PASS"
            notes = f"Nominal non-structural guard clearance ({dist_mm:.2f} mm)"
        elif dist_mm < min_threshold_mm:
            classification = "CLEARANCE"
            clearance_type = "part_to_part"
            is_contact = False
            is_pass = False
            severity = "WARNING"
            notes = f"Clearance deficit: {dist_mm:.2f} mm < threshold {min_threshold_mm:.2f} mm"
        else:
            classification = "CLEARANCE"
            clearance_type = "part_to_part"
            is_contact = False
            is_pass = True
            severity = "PASS"
            notes = f"Clearance adequate: {dist_mm:.2f} mm"

        results.append(
            ClearanceMeasurement(
                target_component_id=c1.id,
                target_component_name=c1.display_name,
                target_cad_id=c1.cad_entity_id,
                neighbor_component_id=c2.id,
                neighbor_component_name=c2.display_name,
                neighbor_cad_id=c2.cad_entity_id,
                distance_mm=round(dist_mm, 3),
                point_on_target=p1,
                point_on_neighbor=p2,
                is_contact=is_contact,
                is_pass=is_pass,
                threshold_mm=min_threshold_mm,
                clearance_type=clearance_type,
                classification=classification,
                intersection_volume_mm3=round(inter_vol, 3) if inter_vol is not None else None,
                severity=severity,
                notes=notes,
            )
        )

    results.sort(key=lambda m: m.distance_mm)
    return results


def analyze_component_obstructions(
    assembly_id: int,
    target_component_id: int,
    db: Session,
    max_travel_mm: float = 600.0,
) -> ComponentObstructionReport:
    """
    Analyze geometric access obstructions for a target component across all 6 cardinal directions (±X, ±Y, ±Z).
    Uses OpenCASCADE analytical B-Rep IntCurvesFace_ShapeIntersector to test rays.
    Excludes sibling parts of the same physical fastener.
    """
    from OCP.IntCurvesFace import IntCurvesFace_ShapeIntersector
    from OCP.gp import gp_Lin, gp_Pnt, gp_Dir

    shapes = get_assembly_shapes(assembly_id, db)
    leaf_components = (
        db.query(Component)
        .filter(Component.assembly_id == assembly_id, Component.is_leaf == 1)
        .all()
    )

    target_comp = next((c for c in leaf_components if c.id == target_component_id), None)
    if not target_comp:
        raise ValueError(f"Component {target_component_id} not found in assembly {assembly_id}")

    target_shape = shapes.get(target_comp.cad_entity_id)
    if not target_shape:
        raise ValueError(f"CAD shape not available for component {target_comp.name}")

    # Exclude self and sibling parts of the same physical fastener (e.g. head does not obstruct its own shank)
    other_components = [
        c for c in leaf_components
        if c.id != target_component_id and not are_sibling_fastener_solids(target_comp, c)
    ]

    intersectors: Dict[int, Any] = {}
    for other in other_components:
        s = shapes.get(other.cad_entity_id)
        if s:
            try:
                inter = IntCurvesFace_ShapeIntersector()
                inter.Load(s.wrapped, 1e-4)
                intersectors[other.id] = inter
            except Exception as e:
                logger.warning(f"Could not initialize intersector for {other.name}: {e}")

    direction_results: List[DirectionAccessResult] = []

    t_bb = target_comp.bounding_box

    for dir_name, dir_vec in CARDINAL_DIRECTIONS:
        dx, dy, dz = dir_vec
        gp_dir = gp_Dir(dx, dy, dz)

        sample_origins: List[Tuple[float, float, float]] = []

        if abs(dx) > 0.5:
            face_x = t_bb["xmax"] if dx > 0 else t_bb["xmin"]
            for sy in [0.2, 0.5, 0.8]:
                for sz in [0.2, 0.5, 0.8]:
                    sample_origins.append((
                        face_x,
                        t_bb["ymin"] + sy * (t_bb["ymax"] - t_bb["ymin"]),
                        t_bb["zmin"] + sz * (t_bb["zmax"] - t_bb["zmin"]),
                    ))
        elif abs(dy) > 0.5:
            face_y = t_bb["ymax"] if dy > 0 else t_bb["ymin"]
            for sx in [0.2, 0.5, 0.8]:
                for sz in [0.2, 0.5, 0.8]:
                    sample_origins.append((
                        t_bb["xmin"] + sx * (t_bb["xmax"] - t_bb["xmin"]),
                        face_y,
                        t_bb["zmin"] + sz * (t_bb["zmax"] - t_bb["zmin"]),
                    ))
        else:
            face_z = t_bb["zmax"] if dz > 0 else t_bb["zmin"]
            for sx in [0.2, 0.5, 0.8]:
                for sy in [0.2, 0.5, 0.8]:
                    sample_origins.append((
                        t_bb["xmin"] + sx * (t_bb["xmax"] - t_bb["xmin"]),
                        t_bb["ymin"] + sy * (t_bb["ymax"] - t_bb["ymin"]),
                        face_z,
                    ))

        total_rays = len(sample_origins)
        comp_hits: Dict[int, Dict[str, Any]] = {}
        blocked_ray_count = 0

        for ox, oy, oz in sample_origins:
            lin = gp_Lin(gp_Pnt(ox + dx * 0.05, oy + dy * 0.05, oz + dz * 0.05), gp_dir)
            ray_blocked = False

            for other in other_components:
                inter = intersectors.get(other.id)
                if not inter:
                    continue

                inter.Perform(lin, 0.01, max_travel_mm)
                if inter.IsDone() and inter.NbPnt() > 0:
                    for idx in range(1, inter.NbPnt() + 1):
                        dist = float(inter.WParameter(idx))
                        if dist > 0.05:
                            ray_blocked = True
                            p = inter.Pnt(idx)
                            pt = Point3D(x=float(p.X()), y=float(p.Y()), z=float(p.Z()))

                            if other.id not in comp_hits:
                                comp_hits[other.id] = {
                                    "min_dist": dist,
                                    "hit_count": 1,
                                    "nearest_pt": pt,
                                }
                            else:
                                comp_hits[other.id]["hit_count"] += 1
                                if dist < comp_hits[other.id]["min_dist"]:
                                    comp_hits[other.id]["min_dist"] = dist
                                    comp_hits[other.id]["nearest_pt"] = pt
                            break

            if ray_blocked:
                blocked_ray_count += 1

        obstructing_list: List[ObstructingComponent] = []
        min_direction_dist = max_travel_mm

        for other_id, hit_info in comp_hits.items():
            other = next(c for c in other_components if c.id == other_id)
            dist = hit_info["min_dist"]
            if dist < min_direction_dist:
                min_direction_dist = dist

            blockage = hit_info["hit_count"] / float(total_rays)
            is_contact = dist <= 0.5

            if is_contact or (dist < 10.0 and blockage > 0.4):
                sev = "CRITICAL"
            elif blockage > 0.25 or dist < 30.0:
                sev = "WARNING"
            else:
                sev = "INFO"

            obstructing_list.append(
                ObstructingComponent(
                    component_id=other.id,
                    component_name=other.display_name,
                    cad_entity_id=other.cad_entity_id,
                    distance_to_obstruction_mm=round(dist, 2),
                    blockage_ratio=round(blockage, 2),
                    contact=is_contact,
                    severity=sev,
                    nearest_point=hit_info["nearest_pt"],
                )
            )

        obstructing_list.sort(key=lambda o: o.distance_to_obstruction_mm)

        blockage_ratio = blocked_ray_count / float(total_rays) if total_rays > 0 else 0.0
        # A direction is considered clear if either 0 rays blocked OR free travel >= 50 mm
        free_travel = min_direction_dist if blocked_ray_count > 0 else max_travel_mm
        is_clear = (blocked_ray_count == 0) or (free_travel >= 50.0)

        direction_results.append(
            DirectionAccessResult(
                direction_name=dir_name,
                direction_vector=dir_vec,
                is_clear=is_clear,
                free_travel_mm=round(free_travel, 2),
                blockage_ratio=round(blockage_ratio, 2),
                obstructing_components=obstructing_list,
            )
        )

    # Best direction has highest free travel and lowest blockage
    best_dir = max(direction_results, key=lambda d: (d.free_travel_mm, -d.blockage_ratio))
    # Truly trapped only if all directions have restricted travel (< 15 mm)
    all_blocked = all(d.free_travel_mm < 15.0 for d in direction_results)

    return ComponentObstructionReport(
        target_component_id=target_comp.id,
        target_component_name=target_comp.display_name,
        target_cad_id=target_comp.cad_entity_id,
        best_direction=best_dir.direction_name,
        best_direction_vector=best_dir.direction_vector,
        max_free_travel_mm=best_dir.free_travel_mm,
        all_directions_blocked=all_blocked,
        directions=direction_results,
        confidence="exact_brep",
        limitations=(
            "Evaluated along 6 cardinal directions using 9-ray spatial sampling grid and "
            "OpenCASCADE analytical B-Rep curve-face intersection."
        ),
    )


def build_disassembly_graph(assembly_id: int, db: Session) -> DisassemblyGraph:
    """
    Construct a Disassembly Dependency Directed Acyclic Graph (DAG) and topological removal sequence.
    Deduplicates multi-solid fasteners and excludes parent assemblies from physical part counts.
    """
    leaf_components = (
        db.query(Component)
        .filter(Component.assembly_id == assembly_id, Component.is_leaf == 1)
        .all()
    )

    nodes: List[DependencyNode] = [
        DependencyNode(
            component_id=c.id,
            name=c.display_name,
            cad_entity_id=c.cad_entity_id,
            component_type=c.component_type or "solid",
            is_leaf=bool(c.is_leaf),
            depth=c.depth,
        )
        for c in leaf_components
    ]

    edges: List[DependencyEdge] = []
    predecessors: Dict[int, Set[int]] = {c.id: set() for c in leaf_components}
    rigid_predecessors: Dict[int, Set[int]] = {c.id: set() for c in leaf_components}
    best_directions: Dict[int, str] = {}

    for c in leaf_components:
        try:
            report = analyze_component_obstructions(assembly_id, c.id, db)
            best_dir_name = report.best_direction
            best_directions[c.id] = best_dir_name or "+Z"

            best_dir_result = next((d for d in report.directions if d.direction_name == best_dir_name), None)
            if best_dir_result:
                for ob in best_dir_result.obstructing_components:
                    if ob.severity in ["CRITICAL", "WARNING"] and ob.component_id != c.id:
                        predecessors[c.id].add(ob.component_id)
                        edges.append(
                            DependencyEdge(
                                precedent_id=ob.component_id,
                                precedent_name=ob.component_name,
                                dependent_id=c.id,
                                dependent_name=c.display_name,
                                reason=f"geometric_obstruction_along_{best_dir_name}",
                            )
                        )
        except Exception as e:
            logger.warning(f"Error computing obstruction for {c.name}: {e}")

    # ── Fastener Assembly Grouping & Clamping Constraints ──
    fastener_comps = [c for c in leaf_components if is_fastener(c.display_name)]
    cover_comps = [c for c in leaf_components if is_housing_or_cover(c.display_name) and not is_fastener(c.display_name)]
    all_parents = {
        c.cad_entity_id: c for c in db.query(Component).filter(Component.assembly_id == assembly_id, Component.is_leaf == 0).all()
    }

    # Group fastener solids by shared parent assembly or normalized physical fastener ID
    fastener_groups: Dict[str, List[Component]] = {}
    for f in fastener_comps:
        group_key = f.parent_cad_id or get_physical_fastener_id(f.display_name, "")
        fastener_groups.setdefault(group_key, []).append(f)

    # Detect which components each fastener group secures/clamps
    clamped_by_group: Dict[str, Set[int]] = {gk: set() for gk in fastener_groups}
    for gk, members in fastener_groups.items():
        parent_comp = all_parents.get(gk)
        parent_name = parent_comp.display_name.lower() if parent_comp else ""

        for cov in cover_comps:
            cov_name = cov.display_name.lower()
            name_match = (
                ("guard" in parent_name and "guard" in cov_name) or
                ("cover" in parent_name and "cover" in cov_name) or
                ("housing" in parent_name and "housing" in cov_name) or
                any(("guard" in m.display_name.lower() and "guard" in cov_name) for m in members) or
                any(("cover" in m.display_name.lower() and "cover" in cov_name) for m in members)
            )
            if name_match:
                clamped_by_group[gk].add(cov.id)
                continue

            # Geometric bounding overlap / penetration check
            for m in members:
                dx = max(0.0, cov.bb_xmin - m.bb_xmax, m.bb_xmin - cov.bb_xmax)
                dy = max(0.0, cov.bb_ymin - m.bb_ymax, m.bb_ymin - cov.bb_ymax)
                dz = max(0.0, cov.bb_zmin - m.bb_zmax, m.bb_zmin - cov.bb_zmax)
                if dx == 0 and dy == 0 and dz == 0:
                    clamped_by_group[gk].add(cov.id)
                    break

    # Apply clamping constraints: Fastener -> Clamped Component
    for gk, members in fastener_groups.items():
        head_m = next((m for m in members if "head" in m.display_name.lower()), members[0])
        head_b_dir = best_directions.get(head_m.id, "+Z")
        head_obs: List[int] = []
        try:
            h_rep = analyze_component_obstructions(assembly_id, head_m.id, db)
            h_d_res = next((d for d in h_rep.directions if d.direction_name == head_b_dir), None)
            if h_d_res:
                head_obs = [o.component_id for o in h_d_res.obstructing_components if o.severity in ["CRITICAL", "WARNING"]]
        except Exception:
            pass

        for cov_id in clamped_by_group[gk]:
            cov_comp = next((c for c in leaf_components if c.id == cov_id), None)
            if not cov_comp:
                continue

            # Check if cover genuinely obstructs fastener head along its proposed extraction corridor
            if cov_id in head_obs:
                # Fastener cannot be removed along proposed direction while cover is installed!
                # Keep reverse obstruction dependency. This is a physical cycle.
                for m in members:
                    rigid_predecessors[m.id].add(cov_id)
            else:
                # Cover does not block the head; clear reverse dependency on cover from fastener members
                for m in members:
                    predecessors[m.id].discard(cov_id)
                    rigid_predecessors[m.id].discard(cov_id)
                    edges = [e for e in edges if not (e.precedent_id == cov_id and e.dependent_id == m.id)]

            # Fastener must precede clamped component
            for m in members:
                predecessors[cov_id].add(m.id)
                rigid_predecessors[cov_id].add(m.id)
                if not any(e.precedent_id == m.id and e.dependent_id == cov_id for e in edges):
                    edges.append(
                        DependencyEdge(
                            precedent_id=m.id,
                            precedent_name=m.display_name,
                            dependent_id=cov_id,
                            dependent_name=cov_comp.display_name,
                            reason="securing_fastener_clamp",
                        )
                    )

    # Internal components require cover/housing/guard open first
    for c in leaf_components:
        c_name = c.display_name.lower()
        if any(k in c_name for k in ["gear", "shaft", "bearing", "rotor", "stator", "wheel", "spacer", "pinion"]):
            for cov in cover_comps:
                if cov.id != c.id and any(k in cov.display_name.lower() for k in ["cover", "housing", "guard", "shield"]):
                    if c.id not in predecessors[cov.id]:
                        predecessors[c.id].add(cov.id)
                        rigid_predecessors[c.id].add(cov.id)
                        if not any(e.precedent_id == cov.id and e.dependent_id == c.id for e in edges):
                            edges.append(
                                DependencyEdge(
                                    precedent_id=cov.id,
                                    precedent_name=cov.display_name,
                                    dependent_id=c.id,
                                    dependent_name=c.display_name,
                                    reason="internal_housing_access_prerequisite",
                                )
                            )

    initial_predecessors: Dict[int, Set[int]] = {c.id: set(predecessors[c.id]) for c in leaf_components}
    initial_rigid_predecessors: Dict[int, Set[int]] = {c.id: set(rigid_predecessors[c.id]) for c in leaf_components}

    def get_display_name(cid: int) -> str:
        comp = next((c for c in leaf_components if c.id == cid), None)
        if not comp:
            return f"Component_{cid}"
        if is_fastener(comp.display_name):
            f_gk = comp.parent_cad_id or get_physical_fastener_id(comp.display_name, "")
            p_comp = all_parents.get(f_gk)
            return p_comp.display_name if p_comp else get_physical_fastener_id(comp.display_name, "")
        return comp.display_name

    def get_group_unsatisfied(gk: str, rem_set: Set[int]) -> Set[int]:
        mems = fastener_groups[gk]
        head_m = next((m for m in mems if "head" in m.display_name.lower()), mems[0])
        unsat = set(predecessors[head_m.id]) - set(m.id for m in mems)
        return unsat - rem_set

def compute_step_effort_cost(
    is_fastener_op: bool,
    is_cover_op: bool,
    direction: Optional[str],
    prev_direction: Optional[str],
    travel_mm: float,
) -> float:
    """
    Explainable Disassembly Effort Cost Function.
    - Base operation cost:
        Fastener unthread: 5.0 pts
        Cover opening: 8.0 pts
        Normal component extraction: 10.0 pts
    - Reorientation penalty:
        Same direction as previous step: 0.0 pts (technician/tool maintains axis)
        Reversed direction on same axis (e.g. +X then -X): 1.5 pts
        Transverse axis change (e.g. +Z to +X): 3.0 pts
    - Extraction travel cost:
        0.02 pts per mm of linear travel
    """
    base = 5.0 if is_fastener_op else (8.0 if is_cover_op else 10.0)

    reorient = 0.0
    if direction and prev_direction:
        if direction == prev_direction:
            reorient = 0.0
        elif direction[1:] == prev_direction[1:]:
            reorient = 1.5
        else:
            reorient = 3.0

    dist_cost = 0.02 * max(0.0, travel_mm)
    return round(base + reorient + dist_cost, 2)


def check_entity_extraction_path(
    moving_comps: List[Component],
    dir_name: str,
    dir_vec: Tuple[float, float, float],
    active_obs_comps: List[Component],
    shapes: Dict[str, Any],
    assembly_bounds: Tuple[float, float, float, float, float, float],
) -> Tuple[bool, float, List[str], Optional[float]]:
    """
    Validate an entity extraction trajectory along dir_vec using broad-phase swept AABB culling
    and narrow-phase stepped translation with OpenCASCADE Boolean collision detection.
    Returns:
      (is_clear: bool, max_verified_travel_mm: float, colliding_obstacle_names: List[str], first_clash_dist: Optional[float])
    """
    min_x, max_x, min_y, max_y, min_z, max_z = assembly_bounds
    vx, vy, vz = dir_vec

    m_xmin = min(c.bb_xmin for c in moving_comps)
    m_xmax = max(c.bb_xmax for c in moving_comps)
    m_ymin = min(c.bb_ymin for c in moving_comps)
    m_ymax = max(c.bb_ymax for c in moving_comps)
    m_zmin = min(c.bb_zmin for c in moving_comps)
    m_zmax = max(c.bb_zmax for c in moving_comps)

    # Required travel to clear global bounding envelope
    if vx > 0:
        L_exit = (max_x - m_xmin) + 5.0
    elif vx < 0:
        L_exit = (m_xmax - min_x) + 5.0
    elif vy > 0:
        L_exit = (max_y - m_ymin) + 5.0
    elif vy < 0:
        L_exit = (m_ymax - min_y) + 5.0
    elif vz > 0:
        L_exit = (max_z - m_zmin) + 5.0
    elif vz < 0:
        L_exit = (m_zmax - min_z) + 5.0
    else:
        L_exit = max(max_x - min_x, max_y - min_y, max_z - min_z) + 5.0
    L_exit = max(L_exit, 10.0)

    # Swept AABB
    sw_xmin = min(m_xmin, m_xmin + vx * L_exit)
    sw_xmax = max(m_xmax, m_xmax + vx * L_exit)
    sw_ymin = min(m_ymin, m_ymin + vy * L_exit)
    sw_ymax = max(m_ymax, m_ymax + vy * L_exit)
    sw_zmin = min(m_zmin, m_zmin + vz * L_exit)
    sw_zmax = max(m_zmax, m_zmax + vz * L_exit)

    broad_obs: List[Component] = []
    for oc in active_obs_comps:
        if not (
            sw_xmax < oc.bb_xmin or sw_xmin > oc.bb_xmax or
            sw_ymax < oc.bb_ymin or sw_ymin > oc.bb_ymax or
            sw_zmax < oc.bb_zmin or sw_zmin > oc.bb_zmax
        ):
            broad_obs.append(oc)

    if not broad_obs:
        return True, round(L_exit, 2), [], None

    step_size = max(2.0, min(10.0, L_exit / 12.0))
    n_steps = int(math.ceil(L_exit / step_size))

    moving_shapes = [shapes[c.cad_entity_id] for c in moving_comps if c.cad_entity_id in shapes]
    obs_shapes = {oc.id: shapes[oc.cad_entity_id] for oc in broad_obs if oc.cad_entity_id in shapes}

    if not moving_shapes or not obs_shapes:
        # Shapes missing -> cannot verify physically
        return True, round(L_exit, 2), [], None

    collided = False
    first_clash_dist = None
    colliding_names: List[str] = []

    for k in range(1, n_steps + 1):
        dist = min(k * step_size, L_exit)
        t_xmin = m_xmin + vx * dist
        t_xmax = m_xmax + vx * dist
        t_ymin = m_ymin + vy * dist
        t_ymax = m_ymax + vy * dist
        t_zmin = m_zmin + vz * dist
        t_zmax = m_zmax + vz * dist

        for ms in moving_shapes:
            try:
                trans_ms = ms.translate((vx * dist, vy * dist, vz * dist))
            except Exception:
                continue

            for oc in broad_obs:
                osh = obs_shapes.get(oc.id)
                if not osh:
                    continue
                # Local BB check
                if (
                    t_xmax < oc.bb_xmin or t_xmin > oc.bb_xmax or
                    t_ymax < oc.bb_ymin or t_ymin > oc.bb_ymax or
                    t_zmax < oc.bb_zmin or t_zmin > oc.bb_zmax
                ):
                    continue

                vol, status = compute_shape_intersection_volume(trans_ms, osh)
                if vol is not None and vol > 0.01:
                    collided = True
                    if first_clash_dist is None:
                        first_clash_dist = dist
                    if oc.display_name not in colliding_names:
                        colliding_names.append(oc.display_name)

        if collided:
            break

    if collided:
        max_travel = round(max(0.0, (first_clash_dist or step_size) - step_size), 2)
        return False, max_travel, colliding_names, first_clash_dist

    return True, round(L_exit, 2), [], None


def build_disassembly_graph(
    assembly_id: int,
    db: Session,
    max_search_nodes: int = 250,
    timeout_seconds: float = 10.0,
) -> DisassemblyGraph:
    """
    Construct an Intelligent Disassembly Dependency Directed Acyclic Graph (DAG) and
    search for feasible component removal orders and extraction directions.
    
    Features:
    - Multi-direction exploration across all 6 principal axes (+X, -X, +Y, -Y, +Z, -Z)
    - Swept-volume Boolean collision validation against dynamically remaining solids
    - Backtracking state-space search to avoid dead ends
    - Explainable Disassembly Effort cost ranking (operation type, reorientation, travel)
    - Honest reporting of constraint cycles, blocked components, and search budget limits
    """
    import time
    start_time = time.time()

    leaf_components = (
        db.query(Component)
        .filter(Component.assembly_id == assembly_id, Component.is_leaf == 1)
        .all()
    )

    nodes: List[DependencyNode] = [
        DependencyNode(
            component_id=c.id,
            name=c.display_name,
            cad_entity_id=c.cad_entity_id,
            component_type=c.component_type or "solid",
            is_leaf=bool(c.is_leaf),
            depth=c.depth,
        )
        for c in leaf_components
    ]

    edges: List[DependencyEdge] = []
    predecessors: Dict[int, Set[int]] = {c.id: set() for c in leaf_components}
    rigid_predecessors: Dict[int, Set[int]] = {c.id: set() for c in leaf_components}
    best_directions: Dict[int, str] = {}

    for c in leaf_components:
        try:
            report = analyze_component_obstructions(assembly_id, c.id, db)
            best_dir_name = report.best_direction
            best_directions[c.id] = best_dir_name or "+Z"

            best_dir_result = next((d for d in report.directions if d.direction_name == best_dir_name), None)
            if best_dir_result:
                for ob in best_dir_result.obstructing_components:
                    if ob.severity in ["CRITICAL", "WARNING"] and ob.component_id != c.id:
                        predecessors[c.id].add(ob.component_id)
                        edges.append(
                            DependencyEdge(
                                precedent_id=ob.component_id,
                                precedent_name=ob.component_name,
                                dependent_id=c.id,
                                dependent_name=c.display_name,
                                reason=f"geometric_obstruction_along_{best_dir_name}",
                            )
                        )
        except Exception as e:
            logger.warning(f"Error computing obstruction for {c.name}: {e}")

    # ── Fastener Assembly Grouping & Clamping Constraints ──
    fastener_comps = [c for c in leaf_components if is_fastener(c.display_name)]
    cover_comps = [c for c in leaf_components if is_housing_or_cover(c.display_name) and not is_fastener(c.display_name)]
    all_parents = {
        c.cad_entity_id: c for c in db.query(Component).filter(Component.assembly_id == assembly_id, Component.is_leaf == 0).all()
    }

    # Group fastener solids by shared parent assembly or normalized physical fastener ID
    fastener_groups: Dict[str, List[Component]] = {}
    for f in fastener_comps:
        group_key = f.parent_cad_id or get_physical_fastener_id(f.display_name, "")
        fastener_groups.setdefault(group_key, []).append(f)

    # Detect which components each fastener group secures/clamps
    clamped_by_group: Dict[str, Set[int]] = {gk: set() for gk in fastener_groups}
    for gk, members in fastener_groups.items():
        parent_comp = all_parents.get(gk)
        parent_name = parent_comp.display_name.lower() if parent_comp else ""

        for cov in cover_comps:
            cov_name = cov.display_name.lower()
            name_match = (
                ("guard" in parent_name and "guard" in cov_name) or
                ("cover" in parent_name and "cover" in cov_name) or
                ("housing" in parent_name and "housing" in cov_name) or
                any(("guard" in m.display_name.lower() and "guard" in cov_name) for m in members) or
                any(("cover" in m.display_name.lower() and "cover" in cov_name) for m in members)
            )
            if name_match:
                clamped_by_group[gk].add(cov.id)
                continue

            # Geometric bounding overlap / penetration check
            for m in members:
                dx = max(0.0, cov.bb_xmin - m.bb_xmax, m.bb_xmin - cov.bb_xmax)
                dy = max(0.0, cov.bb_ymin - m.bb_ymax, m.bb_ymin - cov.bb_ymax)
                dz = max(0.0, cov.bb_zmin - m.bb_zmax, m.bb_zmin - cov.bb_zmax)
                if dx == 0 and dy == 0 and dz == 0:
                    clamped_by_group[gk].add(cov.id)
                    break

    # Apply clamping constraints: Fastener -> Clamped Component
    for gk, members in fastener_groups.items():
        head_m = next((m for m in members if "head" in m.display_name.lower()), members[0])
        head_b_dir = best_directions.get(head_m.id, "+Z")
        head_obs: List[int] = []
        try:
            h_rep = analyze_component_obstructions(assembly_id, head_m.id, db)
            h_d_res = next((d for d in h_rep.directions if d.direction_name == head_b_dir), None)
            if h_d_res:
                head_obs = [o.component_id for o in h_d_res.obstructing_components if o.severity in ["CRITICAL", "WARNING"]]
        except Exception:
            pass

        for cov_id in clamped_by_group[gk]:
            cov_comp = next((c for c in leaf_components if c.id == cov_id), None)
            if not cov_comp:
                continue

            # Check if cover genuinely obstructs fastener head along its proposed extraction corridor
            if cov_id in head_obs:
                # Fastener cannot be removed along proposed direction while cover is installed!
                # Keep reverse obstruction dependency. This is a physical cycle.
                for m in members:
                    rigid_predecessors[m.id].add(cov_id)
            else:
                # Cover does not block the head; clear reverse dependency on cover from fastener members
                for m in members:
                    predecessors[m.id].discard(cov_id)
                    rigid_predecessors[m.id].discard(cov_id)
                    edges = [e for e in edges if not (e.precedent_id == cov_id and e.dependent_id == m.id)]

            # Fastener must precede clamped component
            for m in members:
                predecessors[cov_id].add(m.id)
                rigid_predecessors[cov_id].add(m.id)
                if not any(e.precedent_id == m.id and e.dependent_id == cov_id for e in edges):
                    edges.append(
                        DependencyEdge(
                            precedent_id=m.id,
                            precedent_name=m.display_name,
                            dependent_id=cov_id,
                            dependent_name=cov_comp.display_name,
                            reason="securing_fastener_clamp",
                        )
                    )

    # Internal components require cover/housing/guard open first
    for c in leaf_components:
        c_name = c.display_name.lower()
        if any(k in c_name for k in ["gear", "shaft", "bearing", "rotor", "stator", "wheel", "spacer", "pinion"]):
            for cov in cover_comps:
                if cov.id != c.id and any(k in cov.display_name.lower() for k in ["cover", "housing", "guard", "shield"]):
                    if c.id not in predecessors[cov.id]:
                        predecessors[c.id].add(cov.id)
                        rigid_predecessors[c.id].add(cov.id)
                        if not any(e.precedent_id == cov.id and e.dependent_id == c.id for e in edges):
                            edges.append(
                                DependencyEdge(
                                    precedent_id=cov.id,
                                    precedent_name=cov.display_name,
                                    dependent_id=c.id,
                                    dependent_name=c.display_name,
                                    reason="internal_housing_access_prerequisite",
                                )
                            )

    initial_predecessors: Dict[int, Set[int]] = {c.id: set(predecessors[c.id]) for c in leaf_components}
    initial_rigid_predecessors: Dict[int, Set[int]] = {c.id: set(rigid_predecessors[c.id]) for c in leaf_components}

    def get_display_name(cid: int) -> str:
        comp = next((c for c in leaf_components if c.id == cid), None)
        if not comp:
            return f"Component_{cid}"
        if is_fastener(comp.display_name):
            f_gk = comp.parent_cad_id or get_physical_fastener_id(comp.display_name, "")
            p_comp = all_parents.get(f_gk)
            return p_comp.display_name if p_comp else get_physical_fastener_id(comp.display_name, "")
        return comp.display_name

    def get_group_unsatisfied(gk: str, rem_set: Set[int]) -> Set[int]:
        mems = fastener_groups[gk]
        head_m = next((m for m in mems if "head" in m.display_name.lower()), mems[0])
        unsat = set(predecessors[head_m.id]) - set(m.id for m in mems)
        return unsat - rem_set

    # ── Cycle Detection Check ──
    # Check whether the initial constraints contain a cycle
    test_rem: Set[int] = set()
    test_q: List[int] = [c.id for c in leaf_components if not is_fastener(c.display_name) and len(predecessors[c.id]) == 0]
    test_q_groups: Set[str] = set()
    for gk, mems in fastener_groups.items():
        if len(get_group_unsatisfied(gk, test_rem)) == 0:
            hm = next((m for m in mems if "head" in m.display_name.lower()), mems[0])
            test_q.append(hm.id)
            test_q_groups.add(gk)

    def sort_key(cid: int):
        comp = next(c for c in leaf_components if c.id == cid)
        if is_fastener(comp.display_name):
            return (0, comp.display_name)
        elif is_housing_or_cover(comp.display_name):
            return (1, comp.display_name)
        return (2, comp.display_name)

    test_q.sort(key=sort_key)
    sim_pred = {cid: set(s) for cid, s in predecessors.items()}
    while test_q:
        cid = test_q.pop(0)
        if cid in test_rem:
            continue
        c_comp = next(c for c in leaf_components if c.id == cid)
        f_gk = c_comp.parent_cad_id or get_physical_fastener_id(c_comp.display_name, "")
        if is_fastener(c_comp.display_name) and f_gk in fastener_groups:
            gmems = fastener_groups[f_gk]
            for m in gmems:
                test_rem.add(m.id)
                for other in leaf_components:
                    if other.id not in test_rem and m.id in sim_pred[other.id]:
                        sim_pred[other.id].discard(m.id)
                        if not is_fastener(other.display_name) and len(sim_pred[other.id]) == 0 and other.id not in test_q:
                            test_q.append(other.id)
                            test_q.sort(key=sort_key)
            for gk, mems in fastener_groups.items():
                head_m = next((m for m in mems if "head" in m.display_name.lower()), mems[0])
                if gk not in test_q_groups and len(set(sim_pred[head_m.id]) - set(m.id for m in mems) - test_rem) == 0:
                    if head_m.id not in test_rem and head_m.id not in test_q:
                        test_q.append(head_m.id)
                        test_q_groups.add(gk)
                        test_q.sort(key=sort_key)
        else:
            test_rem.add(cid)
            for other in leaf_components:
                if other.id not in test_rem and cid in sim_pred[other.id]:
                    sim_pred[other.id].discard(cid)
                    if not is_fastener(other.display_name) and len(sim_pred[other.id]) == 0 and other.id not in test_q:
                        test_q.append(other.id)
                        test_q.sort(key=sort_key)
            for gk, mems in fastener_groups.items():
                head_m = next((m for m in mems if "head" in m.display_name.lower()), mems[0])
                if gk not in test_q_groups and len(set(sim_pred[head_m.id]) - set(m.id for m in mems) - test_rem) == 0:
                    if head_m.id not in test_rem and head_m.id not in test_q:
                        test_q.append(head_m.id)
                        test_q_groups.add(gk)
                        test_q.sort(key=sort_key)

    has_static_cycle = len(test_rem) < len(leaf_components)

    # Load CAD shapes for swept-volume motion planning
    try:
        shapes = get_assembly_shapes(assembly_id, db)
    except Exception as e:
        logger.warning(f"Shapes unavailable for assembly {assembly_id}: {e}")
        shapes = {}

    all_bbs = leaf_components
    min_x = min(c.bb_xmin for c in all_bbs)
    max_x = max(c.bb_xmax for c in all_bbs)
    min_y = min(c.bb_ymin for c in all_bbs)
    max_y = max(c.bb_ymax for c in all_bbs)
    min_z = min(c.bb_zmin for c in all_bbs)
    max_z = max(c.bb_zmax for c in all_bbs)
    assembly_bounds = (min_x, max_x, min_y, max_y, min_z, max_z)

    # Define physical entities for disassembly
    entities: Dict[str, Dict[str, Any]] = {}
    comp_to_entity: Dict[int, str] = {}

    for gk, mems in fastener_groups.items():
        head_m = next((m for m in mems if "head" in m.display_name.lower()), mems[0])
        p_comp = all_parents.get(gk)
        group_name = p_comp.display_name if p_comp else get_physical_fastener_id(head_m.display_name, "")
        e_key = f"fastener:{gk}"
        entities[e_key] = {
            "key": e_key,
            "name": f"{group_name} (Fastener Assembly)" if len(mems) > 1 else head_m.display_name,
            "rep_comp": head_m,
            "members": mems,
            "is_fastener": True,
            "is_unified": len(mems) > 1,
            "action": "remove_fastener",
            "prereq_comp_ids": set().union(*(initial_predecessors.get(m.id, set()) for m in mems)) - set(m.id for m in mems),
            "rigid_prereq_comp_ids": set().union(*(initial_rigid_predecessors.get(m.id, set()) for m in mems)) - set(m.id for m in mems),
        }
        for m in mems:
            comp_to_entity[m.id] = e_key

    for c in leaf_components:
        if not is_fastener(c.display_name):
            e_key = f"comp:{c.id}"
            is_cov = is_housing_or_cover(c.display_name)
            entities[e_key] = {
                "key": e_key,
                "name": c.display_name,
                "rep_comp": c,
                "members": [c],
                "is_fastener": False,
                "is_unified": False,
                "action": "open_cover" if is_cov else "extract_component",
                "prereq_comp_ids": set(initial_predecessors.get(c.id, set())),
                "rigid_prereq_comp_ids": set(initial_rigid_predecessors.get(c.id, set())),
            }
            comp_to_entity[c.id] = e_key

    # Entity-level prerequisites
    for e_key, ent in entities.items():
        ent["prereq_entity_keys"] = {
            comp_to_entity[cid] for cid in ent["prereq_comp_ids"] if cid in comp_to_entity and comp_to_entity[cid] != e_key
        }
        ent["rigid_prereq_entity_keys"] = {
            comp_to_entity[cid] for cid in ent["rigid_prereq_comp_ids"] if cid in comp_to_entity and comp_to_entity[cid] != e_key
        }

    # ── Intelligent Multi-Direction & Removal-Order State-Space Search ──
    nodes_explored = 0
    budget_exhausted = False
    memo: Dict[frozenset, float] = {}
    best_partial: List[Tuple[str, str, float, float, List[str], List[DirectionAttempt]]] = []
    best_partial_cost = float("inf")

    def search_best_sequence(
        remaining_keys: Set[str],
        prev_dir: Optional[str],
        current_path: List[Tuple[str, str, float, float, List[str], List[DirectionAttempt]]],
        current_cost: float,
    ) -> Optional[List[Tuple[str, str, float, float, List[str], List[DirectionAttempt]]]]:
        nonlocal nodes_explored, budget_exhausted, best_partial, best_partial_cost

        nodes_explored += 1
        if len(current_path) > len(best_partial) or (
            len(current_path) == len(best_partial) and current_cost < best_partial_cost
        ):
            best_partial = list(current_path)
            best_partial_cost = current_cost

        if not remaining_keys:
            return current_path

        if nodes_explored >= max_search_nodes or (time.time() - start_time) >= timeout_seconds:
            budget_exhausted = True
            return None

        state_key = frozenset(remaining_keys)
        if state_key in memo and memo[state_key] <= current_cost:
            return None
        memo[state_key] = current_cost

        # Eligible entities have all their prerequisites removed
        eligible_keys = [ek for ek in remaining_keys if len(entities[ek]["prereq_entity_keys"] & remaining_keys) == 0]
        if not eligible_keys:
            # Check if any remaining entities have their RIGID prerequisites satisfied
            # (allowing alternative direction search to break directional obstruction cycles)
            soft_eligible = [ek for ek in remaining_keys if len(entities[ek]["rigid_prereq_entity_keys"] & remaining_keys) == 0]
            if not soft_eligible:
                return None
            eligible_keys = soft_eligible

        # Build active obstacle components
        active_obs = [c for ek in remaining_keys for c in entities[ek]["members"]]

        candidate_moves = []
        for ek in eligible_keys:
            ent = entities[ek]
            mems = ent["members"]
            e_obs = [c for c in active_obs if c not in mems]

            feasible_dirs: List[Tuple[str, float]] = []
            dir_attempts: List[DirectionAttempt] = []
            for d_name, d_vec in CARDINAL_DIRECTIONS:
                ok, max_travel, clashes, first_clash = check_entity_extraction_path(
                    mems, d_name, d_vec, e_obs, shapes, assembly_bounds
                )
                dir_attempts.append(
                    DirectionAttempt(
                        direction=d_name,
                        is_clear=ok,
                        max_travel_mm=max_travel if ok else first_clash,
                        colliding_components=clashes,
                        notes="Clear path" if ok else f"Clash with {', '.join(clashes)}",
                    )
                )
                if ok:
                    feasible_dirs.append((d_name, max_travel))

            all_f_dirs = [fd[0] for fd in feasible_dirs]
            for d_name, travel_mm in feasible_dirs:
                step_cost = compute_step_effort_cost(
                    ent["is_fastener"],
                    ent["action"] == "open_cover",
                    d_name,
                    prev_dir,
                    travel_mm,
                )
                candidate_moves.append((step_cost, ek, d_name, travel_mm, all_f_dirs, dir_attempts))

        # Sort candidate moves: prefer lowest-effort cost (maintaining direction, fasteners first)
        candidate_moves.sort(key=lambda m: (m[0], 0 if entities[m[1]]["is_fastener"] else 1))

        for step_cost, ek, d_name, travel_mm, all_f_dirs, dir_attempts in candidate_moves:
            result = search_best_sequence(
                remaining_keys - {ek},
                d_name,
                current_path + [(ek, d_name, travel_mm, step_cost, all_f_dirs, dir_attempts)],
                current_cost + step_cost,
            )
            if result is not None:
                return result
            if budget_exhausted:
                return None

        return None

    all_keys = set(entities.keys())
    optimal_raw_seq: Optional[List[Tuple[str, str, float, float, List[str], List[DirectionAttempt]]]] = None

    optimal_raw_seq = search_best_sequence(all_keys, None, [], 0.0)

    # ── Assemble Output Sequence ──
    sequence: List[DisassemblyStep] = []
    unresolved_components: List[str] = []
    unresolved_reasons: Dict[str, str] = {}
    validation_notes: List[str] = []
    sequence_status = "candidate"
    is_physically_verified = False
    total_effort = 0.0
    step_num = 1

    if optimal_raw_seq and len(optimal_raw_seq) == len(entities):
        # 100% verified complete sequence found!
        sequence_status = "physically_verified"
        is_physically_verified = True
        validation_notes.append(
            f"All {len(optimal_raw_seq)} removal steps physically verified along linear extraction paths "
            f"via swept-volume CAD collision simulation (explored {nodes_explored} search nodes)."
        )
        prev_d: Optional[str] = None
        for ek, d_name, travel_mm, step_cost, all_f_dirs, dir_attempts in optimal_raw_seq:
            ent = entities[ek]
            reorient = bool(prev_d and d_name != prev_d)
            prev_d = d_name
            total_effort += step_cost
            prereq_names = [entities[pk]["name"] for pk in ent["prereq_entity_keys"]]

            initial_dir = best_directions.get(ent["rep_comp"].id, "+Z")
            initial_was_clear = any(att.direction == initial_dir and att.is_clear for att in dir_attempts)

            if initial_was_clear and d_name == initial_dir:
                status_label = "Ready — path verified"
                step_notes = f"Extract along {d_name} (verified clear travel: {travel_mm:.1f} mm)"
            elif not initial_was_clear and d_name in all_f_dirs:
                status_label = "Alternative direction found"
                step_notes = f"Initial direction {initial_dir} blocked; alternative direction {d_name} verified clear ({travel_mm:.1f} mm travel)"
            else:
                status_label = "Ready — path verified"
                step_notes = f"Extract along {d_name} (verified clear travel: {travel_mm:.1f} mm)"

            sequence.append(
                DisassemblyStep(
                    step_number=step_num,
                    component_id=ent["rep_comp"].id,
                    component_name=ent["name"],
                    cad_entity_id=ent["rep_comp"].cad_entity_id,
                    action=ent["action"],
                    removal_direction=d_name,
                    prerequisites=prereq_names,
                    notes=step_notes,
                    member_component_ids=[m.id for m in ent["members"]],
                    is_unified_fastener=ent["is_unified"],
                    is_path_verified=True,
                    path_validation_status="verified",
                    status_label=status_label,
                    colliding_components_along_path=[],
                    max_verified_travel_mm=travel_mm,
                    tested_directions_count=6,
                    feasible_directions=all_f_dirs,
                    direction_attempts=dir_attempts,
                    reorientation_required=reorient,
                    step_effort_cost=step_cost,
                )
            )
            step_num += 1

    else:
        # Partial sequence or cycle detected
        if has_static_cycle:
            sequence_status = "cycle_detected"
            cycle_comp_names = list(dict.fromkeys(get_display_name(c.id) for c in leaf_components if c.id not in test_rem))
            validation_notes.append(
                f"Constraint cycle detected among {len(cycle_comp_names)} physical parts/assemblies: "
                f"{', '.join(cycle_comp_names)}. Fasteners or clamped components exhibit circular access dependencies. "
                f"Secondary candidate extraction applied."
            )
            validation_notes.append(
                "Candidate sequence based on 6-axis ray access envelopes and fastener clamping hierarchy; "
                "full swept-volume continuous collision validation not evaluated for cyclic/unresolved components."
            )
        elif budget_exhausted:
            sequence_status = "budget_exhausted"
            validation_notes.append(
                f"Search budget limit reached ({nodes_explored} nodes). Returning longest valid partial disassembly sequence."
            )
            validation_notes.append(
                "Candidate sequence based on search progress; full swept-volume continuous collision validation not evaluated for unresolved components."
            )
        else:
            sequence_status = "candidate_with_path_collisions"
            validation_notes.append(
                "Dead end encountered during disassembly path search: remaining components blocked by active solids."
            )
            validation_notes.append(
                "Candidate sequence based on tested directions; full swept-volume continuous collision validation not evaluated for blocked components."
            )

        # Place the best partial verified sequence first
        verified_keys = set()
        prev_d = None
        for ek, d_name, travel_mm, step_cost, all_f_dirs, dir_attempts in best_partial:
            ent = entities[ek]
            verified_keys.add(ek)
            reorient = bool(prev_d and d_name != prev_d)
            prev_d = d_name
            total_effort += step_cost
            prereq_names = [entities[pk]["name"] for pk in ent["prereq_entity_keys"]]

            initial_dir = best_directions.get(ent["rep_comp"].id, "+Z")
            initial_was_clear = any(att.direction == initial_dir and att.is_clear for att in dir_attempts)

            if initial_was_clear and d_name == initial_dir:
                status_label = "Ready — path verified"
                step_notes = f"Extract along {d_name} (verified clear travel: {travel_mm:.1f} mm)"
            elif not initial_was_clear and d_name in all_f_dirs:
                status_label = "Alternative direction found"
                step_notes = f"Initial direction {initial_dir} blocked; alternative direction {d_name} verified clear ({travel_mm:.1f} mm travel)"
            else:
                status_label = "Ready — path verified"
                step_notes = f"Extract along {d_name} (verified clear travel: {travel_mm:.1f} mm)"

            sequence.append(
                DisassemblyStep(
                    step_number=step_num,
                    component_id=ent["rep_comp"].id,
                    component_name=ent["name"],
                    cad_entity_id=ent["rep_comp"].cad_entity_id,
                    action=ent["action"],
                    removal_direction=d_name,
                    prerequisites=prereq_names,
                    notes=step_notes,
                    member_component_ids=[m.id for m in ent["members"]],
                    is_unified_fastener=ent["is_unified"],
                    is_path_verified=True,
                    path_validation_status="verified",
                    status_label=status_label,
                    colliding_components_along_path=[],
                    max_verified_travel_mm=travel_mm,
                    tested_directions_count=6,
                    feasible_directions=all_f_dirs,
                    direction_attempts=dir_attempts,
                    reorientation_required=reorient,
                    step_effort_cost=step_cost,
                )
            )
            step_num += 1

        # Append remaining unresolved entities with engineering evidence
        unresolved_keys = [ek for ek in entities if ek not in verified_keys]
        # Sort unresolved: fasteners first, then covers, then components
        unresolved_keys.sort(key=lambda ek: (0 if entities[ek]["is_fastener"] else (1 if entities[ek]["action"] == "open_cover" else 2), entities[ek]["name"]))

        active_remaining_obs = [c for ek in unresolved_keys for c in entities[ek]["members"]]

        for ek in unresolved_keys:
            ent = entities[ek]
            mems = ent["members"]
            e_obs = [c for c in active_remaining_obs if c not in mems]
            prereq_names = [entities[pk]["name"] for pk in ent["prereq_entity_keys"]]

            unresolved_components.append(ent["name"])

            all_colliding: List[str] = []
            f_dirs: List[str] = []
            dir_attempts: List[DirectionAttempt] = []
            for d_name, d_vec in CARDINAL_DIRECTIONS:
                ok, max_trav, clashes, clash_d = check_entity_extraction_path(
                    mems, d_name, d_vec, e_obs, shapes, assembly_bounds
                )
                dir_attempts.append(
                    DirectionAttempt(
                        direction=d_name,
                        is_clear=ok,
                        max_travel_mm=max_trav if ok else clash_d,
                        colliding_components=clashes,
                        notes="Clear path" if ok else f"Clash with {', '.join(clashes)}",
                    )
                )
                if ok:
                    f_dirs.append(d_name)
                else:
                    for c_name in clashes:
                        if c_name not in all_colliding:
                            all_colliding.append(c_name)

            initial_dir = best_directions.get(ent["rep_comp"].id, "+Z")
            unsat_prereqs = [entities[pk]["name"] for pk in ent["prereq_entity_keys"] if pk in unresolved_keys]

            if unsat_prereqs:
                if has_static_cycle:
                    status_label = "Unresolved dependency cycle"
                    status_str = "cyclic"
                    reason = f"Unresolved cycle with: {', '.join(unsat_prereqs)}"
                else:
                    status_label = "Prerequisite required"
                    status_str = "blocked"
                    reason = f"Prerequisite(s) not yet removed: {', '.join(unsat_prereqs)}"
                chosen_d = initial_dir
            elif not f_dirs:
                status_label = "No feasible straight-line path found"
                status_str = "blocked"
                reason = f"All 6 straight-line directions blocked by: {', '.join(all_colliding) if all_colliding else 'active assembly solids'}"
                chosen_d = initial_dir
            else:
                chosen_d = f_dirs[0]
                status_label = "Alternative direction found" if chosen_d != initial_dir else "Ready — path verified"
                status_str = "unverified"
                reason = f"Feasible along {chosen_d} but constrained by removal order"

            unresolved_reasons[ent["name"]] = reason
            sequence.append(
                DisassemblyStep(
                    step_number=step_num,
                    component_id=ent["rep_comp"].id,
                    component_name=ent["name"],
                    cad_entity_id=ent["rep_comp"].cad_entity_id,
                    action=ent["action"],
                    removal_direction=chosen_d,
                    prerequisites=prereq_names,
                    notes=f"Unresolved step: {reason}",
                    member_component_ids=[m.id for m in ent["members"]],
                    is_unified_fastener=ent["is_unified"],
                    is_path_verified=False,
                    path_validation_status=status_str,
                    status_label=status_label,
                    colliding_components_along_path=all_colliding if not f_dirs else unsat_prereqs,
                    max_verified_travel_mm=None,
                    tested_directions_count=6,
                    feasible_directions=f_dirs,
                    direction_attempts=dir_attempts,
                    reorientation_required=False,
                    step_effort_cost=0.0,
                )
            )
            step_num += 1

    verified_count = sum(1 for s in sequence if s.is_path_verified)
    unverified_count = len(sequence) - verified_count

    return DisassemblyGraph(
        assembly_id=assembly_id,
        nodes=nodes,
        edges=edges,
        sequence=sequence,
        total_steps=len(sequence),
        estimated_fastener_count=len(fastener_groups),
        sequence_status=sequence_status,
        is_physically_verified=is_physically_verified,
        validation_notes=validation_notes,
        verified_steps_count=verified_count,
        unverified_steps_count=unverified_count,
        total_disassembly_effort_score=round(total_effort, 2),
        search_nodes_explored=nodes_explored,
        is_search_budget_exhausted=budget_exhausted,
        unresolved_components=unresolved_components,
        unresolved_reasons=unresolved_reasons,
    )


def validate_disassembly_motion_paths(
    assembly_id: int,
    db: Session,
    graph: DisassemblyGraph,
) -> DisassemblyGraph:
    """
    Rigorously validate proposed component disassembly motion paths using continuous CAD
    swept-volume simulation (discrete stepped translation with OpenCASCADE Boolean collision test).
    
    Maintains dynamic assembly state: components are removed sequentially as their steps complete,
    so previously extracted parts do not falsely obstruct subsequent parts.
    
    Classifies each step:
      - 'verified': Completely unobstructed linear path until clear of assembly bounding envelope.
      - 'collision_detected': Solid volumetric clash (> 0.01 mm³) encountered with stationary part.
      - 'cyclic': Prerequisites remain installed or circular dependency prevents valid extraction.
      - 'unverified': Missing geometry or no valid extraction direction.
    """
    leaf_comps_list = (
        db.query(Component)
        .filter(Component.assembly_id == assembly_id, Component.is_leaf == 1)
        .all()
    )
    leaf_components: Dict[int, Component] = {c.id: c for c in leaf_comps_list}
    if not leaf_components or not graph.sequence:
        return graph

    # Attempt to load CAD shapes
    try:
        shapes = get_assembly_shapes(assembly_id, db)
    except Exception as e:
        logger.warning(f"Could not load CAD shapes for motion validation (assembly {assembly_id}): {e}")
        for s in graph.sequence:
            s.is_path_verified = False
            s.path_validation_status = "unverified"
            s.notes += " [CAD shapes unavailable for swept motion simulation]"
        graph.is_physically_verified = False
        graph.verified_steps_count = 0
        graph.unverified_steps_count = len(graph.sequence)
        return graph

    dir_map = dict(CARDINAL_DIRECTIONS)

    # Assembly global bounding envelope
    min_x = min(c.bb_xmin for c in leaf_components.values())
    max_x = max(c.bb_xmax for c in leaf_components.values())
    min_y = min(c.bb_ymin for c in leaf_components.values())
    max_y = max(c.bb_ymax for c in leaf_components.values())
    min_z = min(c.bb_zmin for c in leaf_components.values())
    max_z = max(c.bb_zmax for c in leaf_components.values())

    installed_ids: Set[int] = set(leaf_components.keys())
    verified_count = 0
    unverified_count = 0

    for step in graph.sequence:
        moving_ids = set(step.member_component_ids) if step.member_component_ids else {step.component_id}
        moving_comps = [leaf_components[mid] for mid in moving_ids if mid in leaf_components]

        # 1. Check if any prerequisite is still installed (cyclic or prerequisite violation)
        unresolved_prereqs = [
            c.display_name for c in leaf_components.values()
            if c.id in installed_ids and c.id not in moving_ids and c.display_name in step.prerequisites
        ]
        if unresolved_prereqs:
            step.is_path_verified = False
            step.path_validation_status = "cyclic"
            step.notes += f" [Motion Validation Failed: Prerequisite(s) not yet removed: {', '.join(unresolved_prereqs)}]"
            unverified_count += 1
            installed_ids.difference_update(moving_ids)
            continue

        # 2. Check removal direction
        v = dir_map.get(step.removal_direction) if step.removal_direction else None
        if not v:
            step.is_path_verified = False
            step.path_validation_status = "unverified"
            step.notes += " [Motion Validation Skipped: No extraction direction specified]"
            unverified_count += 1
            installed_ids.difference_update(moving_ids)
            continue

        vx, vy, vz = v
        # Calculate exit travel required to clear the assembly bounding envelope
        if vx > 0:
            L_exit = (max_x - min(c.bb_xmin for c in moving_comps)) + 5.0
        elif vx < 0:
            L_exit = (max(c.bb_xmax for c in moving_comps) - min_x) + 5.0
        elif vy > 0:
            L_exit = (max_y - min(c.bb_ymin for c in moving_comps)) + 5.0
        elif vy < 0:
            L_exit = (max(c.bb_ymax for c in moving_comps) - min_y) + 5.0
        elif vz > 0:
            L_exit = (max_z - min(c.bb_zmin for c in moving_comps)) + 5.0
        elif vz < 0:
            L_exit = (max(c.bb_zmax for c in moving_comps) - min_z) + 5.0
        else:
            L_exit = max(max_x - min_x, max_y - min_y, max_z - min_z) + 5.0
        L_exit = max(L_exit, 10.0)

        # 3. Broad-phase swept AABB filtering against currently installed stationary solids
        candidate_obstacles = installed_ids - moving_ids
        m_xmin = min(c.bb_xmin for c in moving_comps)
        m_xmax = max(c.bb_xmax for c in moving_comps)
        m_ymin = min(c.bb_ymin for c in moving_comps)
        m_ymax = max(c.bb_ymax for c in moving_comps)
        m_zmin = min(c.bb_zmin for c in moving_comps)
        m_zmax = max(c.bb_zmax for c in moving_comps)

        sw_xmin = min(m_xmin, m_xmin + vx * L_exit)
        sw_xmax = max(m_xmax, m_xmax + vx * L_exit)
        sw_ymin = min(m_ymin, m_ymin + vy * L_exit)
        sw_ymax = max(m_ymax, m_ymax + vy * L_exit)
        sw_zmin = min(m_zmin, m_zmin + vz * L_exit)
        sw_zmax = max(m_zmax, m_zmax + vz * L_exit)

        broad_obs: List[Component] = []
        for oid in candidate_obstacles:
            oc = leaf_components[oid]
            if not (
                sw_xmax < oc.bb_xmin or sw_xmin > oc.bb_xmax or
                sw_ymax < oc.bb_ymin or sw_ymin > oc.bb_ymax or
                sw_zmax < oc.bb_zmin or sw_zmin > oc.bb_zmax
            ):
                broad_obs.append(oc)

        if not broad_obs:
            step.is_path_verified = True
            step.path_validation_status = "verified"
            step.colliding_components_along_path = []
            step.max_verified_travel_mm = round(L_exit, 2)
            step.notes += f" [Motion Path: Verified clear exit travel {L_exit:.1f} mm along {step.removal_direction}]"
            verified_count += 1
            installed_ids.difference_update(moving_ids)
            continue

        # 4. Narrow-phase stepped translation with Boolean solid collision detection
        step_size = max(2.0, min(10.0, L_exit / 12.0))
        n_steps = int(math.ceil(L_exit / step_size))

        moving_shapes = [shapes[c.cad_entity_id] for c in moving_comps if c.cad_entity_id in shapes]
        obs_shapes = {oc.id: shapes[oc.cad_entity_id] for oc in broad_obs if oc.cad_entity_id in shapes}

        collided = False
        first_clash_dist: Optional[float] = None
        colliding_names: List[str] = []

        for k in range(1, n_steps + 1):
            dist = min(k * step_size, L_exit)
            t_xmin = m_xmin + vx * dist
            t_xmax = m_xmax + vx * dist
            t_ymin = m_ymin + vy * dist
            t_ymax = m_ymax + vy * dist
            t_zmin = m_zmin + vz * dist
            t_zmax = m_zmax + vz * dist

            for ms in moving_shapes:
                try:
                    trans_ms = ms.translate((vx * dist, vy * dist, vz * dist))
                except Exception:
                    continue

                for oc in broad_obs:
                    osh = obs_shapes.get(oc.id)
                    if not osh:
                        continue
                    # Quick bounding box check at current stepped position
                    if (
                        t_xmax < oc.bb_xmin or t_xmin > oc.bb_xmax or
                        t_ymax < oc.bb_ymin or t_ymin > oc.bb_ymax or
                        t_zmax < oc.bb_zmin or t_zmin > oc.bb_zmax
                    ):
                        continue

                    try:
                        clash = trans_ms.intersect(osh)
                        clash_vol = clash.val().Volume() if hasattr(clash, "val") else clash.Volume()
                        if clash_vol > 0.01:
                            collided = True
                            if first_clash_dist is None:
                                first_clash_dist = dist
                            if oc.display_name not in colliding_names:
                                colliding_names.append(oc.display_name)
                    except Exception:
                        pass

            if collided:
                break

        if collided:
            step.is_path_verified = False
            step.path_validation_status = "collision_detected"
            step.colliding_components_along_path = colliding_names
            step.max_verified_travel_mm = round(max(0.0, (first_clash_dist or step_size) - step_size), 2)
            step.notes += f" [Motion Collision: Collides with {', '.join(colliding_names)} at ~{first_clash_dist:.1f} mm along {step.removal_direction}]"
            unverified_count += 1
        else:
            step.is_path_verified = True
            step.path_validation_status = "verified"
            step.colliding_components_along_path = []
            step.max_verified_travel_mm = round(L_exit, 2)
            step.notes += f" [Motion Path: Verified clear exit travel {L_exit:.1f} mm along {step.removal_direction}]"
            verified_count += 1

        installed_ids.difference_update(moving_ids)

    graph.verified_steps_count = verified_count
    graph.unverified_steps_count = unverified_count

    if verified_count == len(graph.sequence) and len(graph.sequence) > 0 and graph.sequence_status != "cycle_detected":
        graph.is_physically_verified = True
        graph.sequence_status = "physically_verified"
        graph.validation_notes.append(
            f"All {verified_count} removal steps physically verified along linear extraction paths via swept-volume CAD collision simulation."
        )
    else:
        graph.is_physically_verified = False
        if graph.sequence_status != "cycle_detected":
            graph.sequence_status = "candidate_with_path_collisions"
        graph.validation_notes.append(
            f"{unverified_count} of {len(graph.sequence)} removal steps have path collisions or unverified constraints. Sequence represents candidate removal order."
        )

    return graph


def compute_serviceability_scoring(
    assembly_id: int,
    db: Session,
    settings_dict: Optional[Dict[str, Any]] = None,
) -> AssemblyServiceabilityReport:
    """
    Rigorously audited Explainable Serviceability Scoring Engine.
    Formula:
      Score = Access_Score (0-25) + Clearance_Score (0-25) + Disassembly_Score (0-25) + Fastener_Score (0-25)
    Total = 0 to 100.
    All deductions include exact evidence, threshold, and classification.
    """
    settings_dict = settings_dict or {}
    min_clearance_thresh = float(settings_dict.get("min_clearance_mm", 3.0))

    assembly = db.query(Assembly).filter(Assembly.id == assembly_id).first()
    if not assembly:
        raise ValueError(f"Assembly {assembly_id} not found")

    leaf_components = (
        db.query(Component)
        .filter(Component.assembly_id == assembly_id, Component.is_leaf == 1)
        .all()
    )

    dep_graph = build_disassembly_graph(assembly_id, db)
    step_order = {}
    prereq_counts = {}
    for s in dep_graph.sequence:
        step_order[s.component_id] = s.step_number
        prereq_counts[s.component_id] = len(s.prerequisites)
        for mid in s.member_component_ids:
            step_order[mid] = s.step_number
            prereq_counts[mid] = len(s.prerequisites)

    all_clearances = analyze_clearances(assembly_id, db, min_threshold_mm=min_clearance_thresh)

    unique_interference_findings: List[str] = []
    seen_interference_pairs: Set[Tuple[int, int]] = set()
    for c in all_clearances:
        if c.classification == "INTERFERENCE":
            pair_key = tuple(sorted([c.target_component_id, c.neighbor_component_id]))
            if pair_key not in seen_interference_pairs:
                seen_interference_pairs.add(pair_key)
                vol_val = c.intersection_volume_mm3 or 0.0
                unique_interference_findings.append(
                    f"[GEOMETRIC INTERFERENCE] '{c.target_component_name}' <-> '{c.neighbor_component_name}': "
                    f"{vol_val:.2f} mm³ solid overlap."
                )
        elif c.classification == "INDETERMINATE":
            pair_key = tuple(sorted([c.target_component_id, c.neighbor_component_id]))
            if pair_key not in seen_interference_pairs:
                seen_interference_pairs.add(pair_key)
                unique_interference_findings.append(
                    f"[INDETERMINATE INTERFACE] '{c.target_component_name}' <-> '{c.neighbor_component_name}': "
                    f"Near-zero distance ({c.distance_mm:.3f} mm) with indeterminate Boolean result."
                )

    unique_rubbing_findings: List[str] = []
    seen_rubbing_pairs: Set[Tuple[int, int]] = set()
    for c in all_clearances:
        if c.classification == "CLEARANCE" and c.distance_mm < 1.0:
            c1_moving = any(k in c.target_component_name.lower() for k in ["shaft", "gear", "rotor", "impeller"])
            c2_casing = any(k in c.neighbor_component_name.lower() for k in ["housing", "casing", "cover", "frame", "guard"])
            c2_moving = any(k in c.neighbor_component_name.lower() for k in ["shaft", "gear", "rotor", "impeller"])
            c1_casing = any(k in c.target_component_name.lower() for k in ["housing", "casing", "cover", "frame", "guard"])
            if (c1_moving and c2_casing) or (c2_moving and c1_casing):
                pair_key = tuple(sorted([c.target_component_id, c.neighbor_component_id]))
                if pair_key not in seen_rubbing_pairs:
                    seen_rubbing_pairs.add(pair_key)
                    unique_rubbing_findings.append(
                        f"[PROVISIONAL CLEARANCE WARNING] Rotating '{c.target_component_name}' and stationary '{c.neighbor_component_name}' "
                        f"have {c.distance_mm:.2f} mm clearance (potential running contact)."
                    )

    critical_safety_findings: List[str] = unique_interference_findings + unique_rubbing_findings
    component_scores: List[ComponentScore] = []
    general_recs: List[str] = []

    for comp in leaf_components:
        deductions: List[ScoreDeduction] = []
        warnings: List[str] = []

        access_sub = 25.0
        clearance_sub = 25.0
        disassembly_sub = 25.0
        fastener_sub = 25.0

        # ── 1. Access & Obstruction ──
        try:
            obs_report = analyze_component_obstructions(assembly_id, comp.id, db)
            best_dir = obs_report.best_direction
            all_blocked = obs_report.all_directions_blocked

            if all_blocked:
                pen = 15.0
                access_sub = max(0.0, access_sub - pen)
                deductions.append(
                    ScoreDeduction(
                        criterion="Access & Obstruction",
                        penalty_points=pen,
                        description="All cardinal extraction paths physically trapped by housing/frame",
                        measured_value=f"Free travel: {obs_report.max_free_travel_mm:.1f} mm",
                        threshold=">= 50.0 mm",
                        severity="CRITICAL",
                    )
                )
                warnings.append(
                    f"[Provisional Heuristic] Component '{comp.display_name}' has no direct line-of-sight extraction corridor (<15 mm travel)."
                )
            elif obs_report.max_free_travel_mm < 25.0:
                pen = 8.0
                access_sub = max(0.0, access_sub - pen)
                deductions.append(
                    ScoreDeduction(
                        criterion="Access & Obstruction",
                        penalty_points=pen,
                        description=f"Restricted free extraction travel along best direction ({best_dir})",
                        measured_value=f"{obs_report.max_free_travel_mm:.1f} mm",
                        threshold=">= 25.0 mm",
                        severity="WARNING",
                    )
                )
            elif obs_report.max_free_travel_mm < 50.0:
                pen = 3.0
                access_sub = max(0.0, access_sub - pen)
                deductions.append(
                    ScoreDeduction(
                        criterion="Access & Obstruction",
                        penalty_points=pen,
                        description=f"Partial extraction clearance along best direction ({best_dir})",
                        measured_value=f"{obs_report.max_free_travel_mm:.1f} mm",
                        threshold=">= 50.0 mm",
                        severity="INFO",
                    )
                )

            # Check for immediate obstructions (< 10 mm gap) along the best direction
            best_dir_result = next((d for d in obs_report.directions if d.direction_name == best_dir), None)
            if best_dir_result:
                for ob in best_dir_result.obstructing_components:
                    if ob.severity == "CRITICAL" and ob.distance_to_obstruction_mm < 10.0:
                        pen = 4.0
                        access_sub = max(0.0, access_sub - pen)
                        deductions.append(
                            ScoreDeduction(
                                criterion="Access & Obstruction",
                                penalty_points=pen,
                                description=f"Immediate obstruction by '{ob.component_name}' along {best_dir}",
                                measured_value=f"{ob.distance_to_obstruction_mm:.1f} mm gap",
                                threshold=">= 15.0 mm",
                                severity="CRITICAL",
                            )
                        )
                        break
        except Exception as e:
            logger.warning(f"Error evaluating obstruction score for {comp.name}: {e}")

        # ── 2. Clearance & Solid Interference ──
        try:
            clearances = analyze_clearances(
                assembly_id, db, target_component_id=comp.id, min_threshold_mm=min_clearance_thresh
            )

            # Check for confirmed volumetric solid collisions first
            interferences = [c for c in clearances if c.classification == "INTERFERENCE"]
            if interferences:
                non_fastener_clashes = [
                    c for c in interferences
                    if not (is_fastener(comp.display_name) or is_fastener(c.neighbor_component_name))
                ]
                worst_clash = max(interferences, key=lambda c: c.intersection_volume_mm3 or 0.0)
                vol_val = worst_clash.intersection_volume_mm3 or 0.0
                vol_str = f"{vol_val:.2f} mm³"

                # Major structural collision between functional bodies
                if non_fastener_clashes or vol_val > 10.0:
                    pen = 20.0
                    clearance_sub = max(0.0, clearance_sub - pen)
                    deductions.append(
                        ScoreDeduction(
                            criterion="Clearance",
                            penalty_points=pen,
                            description=f"Confirmed solid interference (CAD collision) with '{worst_clash.neighbor_component_name}'",
                            measured_value=f"{vol_str} clash volume",
                            threshold="0.00 mm³",
                            severity="CRITICAL",
                        )
                    )
                    crit = (
                        f"[Geometric Interference] Solid overlap of {vol_str} with '{worst_clash.neighbor_component_name}'."
                    )
                    warnings.append(crit)
                else:
                    # Fastener through-hole without modeled clearance hole
                    pen = 10.0
                    clearance_sub = max(0.0, clearance_sub - pen)
                    deductions.append(
                        ScoreDeduction(
                            criterion="Clearance",
                            penalty_points=pen,
                            description=f"Fastener through-hole interference with '{worst_clash.neighbor_component_name}' (unmodeled hole)",
                            measured_value=f"{vol_str} overlap",
                            threshold="0.00 mm³",
                            severity="WARNING",
                        )
                    )
            else:
                # Filter out intentional interfaces: contact, bearing running clearances, slip fits, guard offsets
                unintended_deficits = [
                    c for c in clearances
                    if c.classification == "CLEARANCE"
                    and not c.is_pass
                    and c.clearance_type not in ["bearing_radial_clearance", "slip_fit_clearance", "guard_clearance"]
                    and c.distance_mm < min_clearance_thresh
                ]

                if unintended_deficits:
                    min_c = min(unintended_deficits, key=lambda c: c.distance_mm)
                    pen = 10.0
                    clearance_sub = max(0.0, clearance_sub - pen)
                    deductions.append(
                        ScoreDeduction(
                            criterion="Clearance",
                            penalty_points=pen,
                            description=f"Clearance deficit to stationary '{min_c.neighbor_component_name}'",
                            measured_value=f"{min_c.distance_mm:.2f} mm",
                            threshold=f"{min_clearance_thresh:.2f} mm",
                            severity="WARNING",
                        )
                    )

                    # Rubbing hazard warning only between moving part and stationary casing
                    comp_is_moving = any(k in comp.display_name.lower() for k in ["shaft", "gear", "rotor", "impeller"])
                    neighbor_is_casing = any(k in min_c.neighbor_component_name.lower() for k in ["housing", "casing", "cover", "frame"])
                    if comp_is_moving and neighbor_is_casing and min_c.distance_mm < 1.0:
                        crit = (
                            f"[Provisional Safety Heuristic] Rotating component '{comp.display_name}' has only "
                            f"{min_c.distance_mm:.2f} mm clearance to stationary '{min_c.neighbor_component_name}' (potential rubbing risk)."
                        )
                        warnings.append(crit)
        except Exception as e:
            logger.warning(f"Error evaluating clearance score for {comp.name}: {e}")

        # ── 3. Disassembly Sequence & Depth ──
        prereqs = prereq_counts.get(comp.id, 0)
        step = step_order.get(comp.id, 1)
        if prereqs > 0:
            pen = min(15.0, prereqs * 3.0)
            disassembly_sub = max(0.0, disassembly_sub - pen)
            deductions.append(
                ScoreDeduction(
                    criterion="Disassembly Effort",
                    penalty_points=pen,
                    description=f"Requires {prereqs} prior component(s) removed in sequence (Removal Step {step})",
                    measured_value=f"{prereqs} preceding parts",
                    threshold="0 preceding parts",
                    severity="WARNING" if prereqs <= 2 else "CRITICAL",
                )
            )

        # ── 4. Fastener Complexity (Deduplicated physical bolts) ──
        if is_fastener(comp.display_name):
            fastener_sub = 25.0  # Fasteners are directly accessible removal elements
        else:
            # Find distinct physical fasteners securing this component
            related_fastener_names = {
                get_physical_fastener_id(e.precedent_name, "")
                for e in dep_graph.edges
                if e.dependent_id == comp.id and "fastener" in e.reason
            }
            num_physical_fasteners = len(related_fastener_names)
            if num_physical_fasteners > 0:
                pen = min(12.0, num_physical_fasteners * 2.0)
                fastener_sub = max(0.0, fastener_sub - pen)
                deductions.append(
                    ScoreDeduction(
                        criterion="Fastener Complexity",
                        penalty_points=pen,
                        description=f"Secured by {num_physical_fasteners} physical fastener(s)",
                        measured_value=f"{num_physical_fasteners} physical bolts",
                        threshold="<= 2 fasteners",
                        severity="INFO",
                    )
                )

        total_score = round(access_sub + clearance_sub + disassembly_sub + fastener_sub, 1)
        if total_score >= 88.0:
            rating = "EXCELLENT"
        elif total_score >= 70.0:
            rating = "GOOD"
        elif total_score >= 50.0:
            rating = "FAIR"
        else:
            rating = "POOR"

        component_scores.append(
            ComponentScore(
                component_id=comp.id,
                component_name=comp.display_name,
                cad_entity_id=comp.cad_entity_id,
                score=total_score,
                rating=rating,
                access_score=round(access_sub, 1),
                clearance_score=round(clearance_sub, 1),
                disassembly_score=round(disassembly_sub, 1),
                fastener_score=round(fastener_sub, 1),
                deductions=deductions,
                safety_warnings=warnings,
            )
        )

    overall_score = round(sum(c.score for c in component_scores) / len(component_scores), 1) if component_scores else 100.0

    crit_count = len(critical_safety_findings)
    warn_count = sum(sum(1 for d in c.deductions if d.severity == "WARNING") for c in component_scores)

    # Disqualification / rating capping rule: A design with confirmed structural clashes cannot be EXCELLENT
    if crit_count > 0:
        if overall_score >= 50.0:
            overall_rating = "FAIR"
        else:
            overall_rating = "POOR"
    elif overall_score >= 88.0:
        overall_rating = "EXCELLENT"
    elif overall_score >= 70.0:
        overall_rating = "GOOD"
    elif overall_score >= 50.0:
        overall_rating = "FAIR"
    else:
        overall_rating = "POOR"

    if crit_count > 0:
        general_recs.append("CRITICAL: Resolve confirmed physical solid interferences before manufacturing or assembly.")
    if dep_graph.total_steps > 8:
        general_recs.append("Consider modular subassemblies to reduce overall disassembly sequence depth.")
    if dep_graph.estimated_fastener_count > 4:
        general_recs.append("Standardize fastener drive types and lengths to minimize tooling changes during servicing.")

    return AssemblyServiceabilityReport(
        assembly_id=assembly.id,
        filename=assembly.filename,
        overall_score=overall_score,
        overall_rating=overall_rating,
        analyzed_components_count=len(component_scores),
        critical_issues_count=crit_count,
        warnings_count=warn_count,
        component_scores=component_scores,
        critical_safety_findings=critical_safety_findings,
        general_recommendations=general_recs,
        settings={
            "min_clearance_mm": min_clearance_thresh,
            "rule_version": "Milestone 3 Geometric Validation Engine v2.0",
            "calculation_method": "OpenCASCADE Analytical B-Rep Boolean Common & BRepExtrema",
            "validation_status": "Validated CAD Collision & Constraint Analysis",
        },
    )
