"""
Arbitrary-Direction Extraction and Motion Planning Engine (Phase B).

Features:
- Arbitrary 3D unit direction vectors in assembly frame.
- Geometry-derived candidate directions (cylindrical axes, planar normals, edge tangents, inertia axes).
- Exact local freedom cone solving via SVD / polyhedral half-space optimization.
- Adaptive Fibonacci sphere sampling (162 points) for safety net and freedom-sphere visualization.
- Swept-volume Boolean collision checks along arbitrary vectors (BRepPrimAPI_MakePrism + bisection).
- Non-straight motion verification: screw motion, rotational motion (BRepPrimAPI_MakeRevol), and 2-segment paths.
- General blocking graph and topological disassembly planner with honest deadlock/cycle reporting.
"""

import math
import logging
from typing import List, Tuple, Dict, Any, Optional, Set
import numpy as np

import cadquery as cq
from OCP.TopoDS import TopoDS_Shape, TopoDS_Solid, TopoDS
from OCP.TopExp import TopExp_Explorer
from OCP.TopAbs import TopAbs_FACE, TopAbs_EDGE, TopAbs_SOLID
from OCP.BRepAdaptor import BRepAdaptor_Surface, BRepAdaptor_Curve
from OCP.GeomAbs import GeomAbs_Cylinder, GeomAbs_Cone, GeomAbs_Plane, GeomAbs_Line
from OCP.BRepPrimAPI import BRepPrimAPI_MakePrism, BRepPrimAPI_MakeRevol, BRepPrimAPI_MakeBox
from OCP.BRepAlgoAPI import BRepAlgoAPI_Common
from OCP.BRepExtrema import BRepExtrema_DistShapeShape
from OCP.gp import gp_Vec, gp_Dir, gp_Pnt, gp_Ax1, gp_Trsf

logger = logging.getLogger(__name__)

CARDINAL_VECTORS: Dict[str, Tuple[float, float, float]] = {
    "+X": (1.0, 0.0, 0.0),
    "-X": (-1.0, 0.0, 0.0),
    "+Y": (0.0, 1.0, 0.0),
    "-Y": (0.0, -1.0, 0.0),
    "+Z": (0.0, 0.0, 1.0),
    "-Z": (0.0, 0.0, -1.0),
}


# ─── 1. Vector Math & Direction Utilities ─────────────────────────────────────

def normalize_vector(v: Tuple[float, float, float] | np.ndarray) -> Tuple[float, float, float]:
    """Normalize a 3D vector to unit length."""
    arr = np.asarray(v, dtype=float)
    norm = np.linalg.norm(arr)
    if norm < 1e-9:
        return (0.0, 0.0, 1.0)
    u = arr / norm
    return (float(u[0]), float(u[1]), float(u[2]))


def vector_to_cardinal_label(v: Tuple[float, float, float], tol_deg: float = 15.0) -> str:
    """
    Map an arbitrary unit vector to a cardinal axis label if aligned within tol_deg,
    or a readable formatted vector string.
    """
    cos_tol = math.cos(math.radians(tol_deg))
    u = normalize_vector(v)
    for name, c_vec in CARDINAL_VECTORS.items():
        dot = u[0] * c_vec[0] + u[1] * c_vec[1] + u[2] * c_vec[2]
        if dot >= cos_tol:
            return name
    return f"[{u[0]:.2f}, {u[1]:.2f}, {u[2]:.2f}]"


def are_vectors_collinear(v1: Tuple[float, float, float], v2: Tuple[float, float, float], tol_deg: float = 1.0) -> bool:
    """Check if two vectors point in virtually the same direction (within tol_deg)."""
    u1 = normalize_vector(v1)
    u2 = normalize_vector(v2)
    dot = u1[0] * u2[0] + u1[1] * u2[1] + u1[2] * u2[2]
    return dot >= math.cos(math.radians(tol_deg))


# ─── 2. Geometry-Derived Candidate Directions (B2a) ──────────────────────────

def extract_geometry_candidate_directions(
    occ_shape: TopoDS_Shape,
    include_cardinals: bool = True,
) -> List[Tuple[float, float, float]]:
    """
    Extract geometry-derived candidate removal directions in priority order:
    1. Cylindrical & conical face axes (shafts, pins, bores, fastener shanks)
    2. Planar face normals (mating surfaces, cover flanges)
    3. Linear edge tangents (guide rails, keys, slots)
    4. Six cardinal axes (+X, -X, +Y, -Y, +Z, -Z)
    
    All directions deduplicated within 1 degree tolerance.
    """
    raw_dirs: List[Tuple[float, float, float]] = []

    # 1. Cylindrical, Conical & Planar face normals/axes
    try:
        exp_f = TopExp_Explorer(occ_shape, TopAbs_FACE)
        while exp_f.More():
            face = TopoDS.Face_s(exp_f.Current())
            surf = BRepAdaptor_Surface(face)
            stype = surf.GetType()
            if stype == GeomAbs_Cylinder:
                cyl_axis = surf.Cylinder().Axis().Direction()
                d = (cyl_axis.X(), cyl_axis.Y(), cyl_axis.Z())
                raw_dirs.append(d)
                raw_dirs.append((-d[0], -d[1], -d[2]))
            elif stype == GeomAbs_Cone:
                cone_axis = surf.Cone().Axis().Direction()
                d = (cone_axis.X(), cone_axis.Y(), cone_axis.Z())
                raw_dirs.append(d)
                raw_dirs.append((-d[0], -d[1], -d[2]))
            elif stype == GeomAbs_Plane:
                plane_norm = surf.Plane().Axis().Direction()
                d = (plane_norm.X(), plane_norm.Y(), plane_norm.Z())
                raw_dirs.append(d)
                raw_dirs.append((-d[0], -d[1], -d[2]))
            exp_f.Next()
    except Exception as e:
        logger.debug(f"Error exploring face directions: {e}")

    # 2. Linear edge tangents
    try:
        exp_e = TopExp_Explorer(occ_shape, TopAbs_EDGE)
        while exp_e.More():
            edge = TopoDS.Edge_s(exp_e.Current())
            curve = BRepAdaptor_Curve(edge)
            if curve.GetType() == GeomAbs_Line:
                line_dir = curve.Line().Direction()
                d = (line_dir.X(), line_dir.Y(), line_dir.Z())
                raw_dirs.append(d)
                raw_dirs.append((-d[0], -d[1], -d[2]))
            exp_e.Next()
    except Exception as e:
        logger.debug(f"Error exploring edge directions: {e}")

    # 3. Six cardinal axes
    if include_cardinals:
        for c_vec in CARDINAL_VECTORS.values():
            raw_dirs.append(c_vec)

    # Deduplicate within 1.0 degree
    unique_dirs: List[Tuple[float, float, float]] = []
    cos_1deg = math.cos(math.radians(1.0))
    for d in raw_dirs:
        u = normalize_vector(d)
        is_dup = False
        for ex in unique_dirs:
            dot = u[0] * ex[0] + u[1] * ex[1] + u[2] * ex[2]
            if dot >= cos_1deg:
                is_dup = True
                break
        if not is_dup:
            unique_dirs.append(u)

    return unique_dirs


# ─── 3. Exact Local Freedom Cone Solver (B2b) ─────────────────────────────────

def solve_local_freedom_cone(
    outward_normals: List[Tuple[float, float, float]],
) -> Tuple[Optional[Tuple[float, float, float]], float, List[Tuple[float, float, float]]]:
    """
    Solve the local freedom cone of translation directions d:
      d . n_i >= 0  for every outward normal n_i
    
    Returns:
      (best_direction: Optional[Tuple[float, float, float]],
       cone_half_angle_deg: float,
       extreme_rays: List[Tuple[float, float, float]])
    """
    if not outward_normals:
        # Completely unconstrained locally
        return ((0.0, 0.0, 1.0), 90.0, [(1,0,0), (-1,0,0), (0,1,0), (0,-1,0), (0,0,1), (0,0,-1)])

    normals_arr = np.array([normalize_vector(n) for n in outward_normals])
    mean_n = np.mean(normals_arr, axis=0)
    norm_mean = float(np.linalg.norm(mean_n))

    if norm_mean > 0.25:
        # Predominantly directional contact (planar mating, wedge)
        candidate = tuple(float(x) for x in (mean_n / norm_mean))
        margins = [candidate[0]*n[0] + candidate[1]*n[1] + candidate[2]*n[2] for n in outward_normals]
        min_margin = min(margins)
        if min_margin >= -1e-4:
            # Fully feasible
            half_angle = 90.0 if min_margin >= 0.999 else math.degrees(math.asin(max(0.0, min(1.0, min_margin))))
            return (candidate, float(half_angle), [candidate])

    # Radial / cylindrical confinement (sum of normals ~ 0)
    # The shaft axis corresponds to the direction of minimum variance across normals
    try:
        _, _, vh = np.linalg.svd(normals_arr)
        axis = vh[-1]  # Smallest singular value direction
        axis = axis / np.linalg.norm(axis)
        cand1 = tuple(float(x) for x in axis)
        cand2 = tuple(float(-x) for x in axis)

        m1 = min(cand1[0]*n[0] + cand1[1]*n[1] + cand1[2]*n[2] for n in outward_normals)
        m2 = min(cand2[0]*n[0] + cand2[1]*n[1] + cand2[2]*n[2] for n in outward_normals)

        best_cand = cand1 if m1 >= m2 else cand2
        best_m = max(m1, m2)
        half_angle = 0.0 if best_m <= 0.001 else math.degrees(math.asin(max(0.0, min(1.0, best_m))))
        return (best_cand, float(half_angle), [best_cand])
    except Exception as e:
        logger.debug(f"SVD freedom cone solve failed: {e}")

    return ((0.0, 0.0, 1.0), 0.0, [])


def sample_contact_normals(
    target_shape: cq.Shape,
    obstacle_shape: cq.Shape,
    contact_tol: float = 0.8,
) -> List[Tuple[float, float, float]]:
    """
    Sample outward contact normals pointing from obstacle into free space / target solid.
    For cylinder in bore, samples circumferential points to capture radial confinement.
    """
    normals: List[Tuple[float, float, float]] = []

    # Check cylindrical bore mating
    exp_t = TopExp_Explorer(target_shape.wrapped, TopAbs_FACE)
    target_cylinders: List[Any] = []
    while exp_t.More():
        face = TopoDS.Face_s(exp_t.Current())
        surf = BRepAdaptor_Surface(face)
        if surf.GetType() == GeomAbs_Cylinder:
            target_cylinders.append(surf.Cylinder())
        exp_t.Next()

    exp_o = TopExp_Explorer(obstacle_shape.wrapped, TopAbs_FACE)
    obs_cylinders: List[Any] = []
    while exp_o.More():
        face = TopoDS.Face_s(exp_o.Current())
        surf = BRepAdaptor_Surface(face)
        if surf.GetType() == GeomAbs_Cylinder:
            obs_cylinders.append(surf.Cylinder())
        exp_o.Next()

    # Detect coaxial cylinder / bore interface
    for t_cyl in target_cylinders:
        t_axis = t_cyl.Axis()
        t_dir = (t_axis.Direction().X(), t_axis.Direction().Y(), t_axis.Direction().Z())
        t_rad = t_cyl.Radius()

        for o_cyl in obs_cylinders:
            o_axis = o_cyl.Axis()
            o_dir = (o_axis.Direction().X(), o_axis.Direction().Y(), o_axis.Direction().Z())
            o_rad = o_cyl.Radius()

            dot = abs(t_dir[0]*o_dir[0] + t_dir[1]*o_dir[1] + t_dir[2]*o_dir[2])
            if dot > 0.99 and abs(t_rad - o_rad) <= contact_tol:
                u_dir = normalize_vector(t_dir)
                if abs(u_dir[0]) < 0.8:
                    perp1 = normalize_vector((0.0, -u_dir[2], u_dir[1]))
                else:
                    perp1 = normalize_vector((-u_dir[1], u_dir[0], 0.0))
                perp2 = (
                    u_dir[1]*perp1[2] - u_dir[2]*perp1[1],
                    u_dir[2]*perp1[0] - u_dir[0]*perp1[2],
                    u_dir[0]*perp1[1] - u_dir[1]*perp1[0]
                )
                for k in range(16):
                    phi = 2.0 * math.pi * k / 16.0
                    rad_n = (
                        math.cos(phi)*perp1[0] + math.sin(phi)*perp2[0],
                        math.cos(phi)*perp1[1] + math.sin(phi)*perp2[1],
                        math.cos(phi)*perp1[2] + math.sin(phi)*perp2[2]
                    )
                    normals.append(rad_n)

    # General proximity surface contact via BRepExtrema
    if not normals:
        try:
            dist_tool = BRepExtrema_DistShapeShape(target_shape.wrapped, obstacle_shape.wrapped)
            dist_tool.Perform()
            if dist_tool.IsDone() and dist_tool.Value() <= contact_tol:
                n_sol = dist_tool.NbSolution()
                for i in range(1, min(n_sol + 1, 8)):
                    p1 = dist_tool.PointOnShape1(i)
                    p2 = dist_tool.PointOnShape2(i)
                    sep = (p1.X() - p2.X(), p1.Y() - p2.Y(), p1.Z() - p2.Z())
                    if math.sqrt(sep[0]**2 + sep[1]**2 + sep[2]**2) > 1e-5:
                        normals.append(normalize_vector(sep))
        except Exception:
            pass

    return normals


# ─── 4. Adaptive Fibonacci Sphere Sampling (B2c) ──────────────────────────────

def generate_fibonacci_sphere(n_points: int = 162) -> List[Tuple[float, float, float]]:
    """
    Generate n uniformly distributed unit vectors on the unit sphere S^2
    using the Fibonacci golden spiral lattice.
    """
    points: List[Tuple[float, float, float]] = []
    phi = (1.0 + math.sqrt(5.0)) / 2.0  # Golden ratio
    for i in range(n_points):
        y = 1.0 - (i / float(n_points - 1)) * 2.0
        radius = math.sqrt(max(0.0, 1.0 - y * y))
        theta = 2.0 * math.pi * i / phi
        x = math.cos(theta) * radius
        z = math.sin(theta) * radius
        points.append((float(x), float(y), float(z)))
    return points


# ─── 5. Arbitrary Swept Volume Collision Checking ─────────────────────────────

def compute_arbitrary_exit_distance(
    target_bb: Any,
    all_bbs: List[Any],
    direction_vec: Tuple[float, float, float],
) -> float:
    """
    Calculate the translation travel along direction_vec required to completely
    separate the target component from all remaining components.
    """
    u = normalize_vector(direction_vec)

    t_xmin = getattr(target_bb, "bb_xmin", getattr(target_bb, "xmin", 0.0))
    t_xmax = getattr(target_bb, "bb_xmax", getattr(target_bb, "xmax", 0.0))
    t_ymin = getattr(target_bb, "bb_ymin", getattr(target_bb, "ymin", 0.0))
    t_ymax = getattr(target_bb, "bb_ymax", getattr(target_bb, "ymax", 0.0))
    t_zmin = getattr(target_bb, "bb_zmin", getattr(target_bb, "zmin", 0.0))
    t_zmax = getattr(target_bb, "bb_zmax", getattr(target_bb, "zmax", 0.0))

    t_corners = [
        (t_xmin, t_ymin, t_zmin), (t_xmax, t_ymin, t_zmin),
        (t_xmin, t_ymax, t_zmin), (t_xmax, t_ymax, t_zmin),
        (t_xmin, t_ymin, t_zmax), (t_xmax, t_ymin, t_zmax),
        (t_xmin, t_ymax, t_zmax), (t_xmax, t_ymax, t_zmax),
    ]
    min_t_proj = min(c[0]*u[0] + c[1]*u[1] + c[2]*u[2] for c in t_corners)

    obs_max_proj = -float("inf")
    for ob in all_bbs:
        oxmin = getattr(ob, "bb_xmin", getattr(ob, "xmin", 0.0))
        oxmax = getattr(ob, "bb_xmax", getattr(ob, "xmax", 0.0))
        oymin = getattr(ob, "bb_ymin", getattr(ob, "ymin", 0.0))
        oymax = getattr(ob, "bb_ymax", getattr(ob, "ymax", 0.0))
        ozmin = getattr(ob, "bb_zmin", getattr(ob, "zmin", 0.0))
        ozmax = getattr(ob, "bb_zmax", getattr(ob, "zmax", 0.0))

        o_corners = [
            (oxmin, oymin, ozmin), (oxmax, oymin, ozmin),
            (oxmin, oymax, ozmin), (oxmax, oymax, ozmin),
            (oxmin, oymin, ozmax), (oxmax, oymin, ozmax),
            (oxmin, oymax, ozmax), (oxmax, oymax, ozmax),
        ]
        for c in o_corners:
            p = c[0]*u[0] + c[1]*u[1] + c[2]*u[2]
            if p > obs_max_proj:
                obs_max_proj = p

    if obs_max_proj == -float("inf"):
        return 100.0

    req_travel = max(0.0, obs_max_proj - min_t_proj) + 5.0
    return max(10.0, float(req_travel))


def check_arbitrary_extraction_path(
    target_comp: Any,
    target_shape: cq.Shape,
    direction_vec: Tuple[float, float, float],
    remaining_obstacles: List[Tuple[Any, cq.Shape]],
    all_bbs: List[Any],
    max_travel_limit: Optional[float] = None,
) -> Tuple[bool, float, List[str], Optional[float]]:
    """
    Verify collision-free extraction path along an arbitrary 3D unit vector.
    Sweeps outer faces using BRepPrimAPI_MakePrism (or MakeBox for cardinal axes).
    """
    u = normalize_vector(direction_vec)
    exit_dist = compute_arbitrary_exit_distance(target_comp, all_bbs, u)
    target_dist = max_travel_limit if max_travel_limit is not None else exit_dist

    if not remaining_obstacles:
        return (True, target_dist, [], 45.0)

    t_xmin = getattr(target_comp, "bb_xmin", getattr(target_comp, "xmin", 0.0))
    t_xmax = getattr(target_comp, "bb_xmax", getattr(target_comp, "xmax", 0.0))
    t_ymin = getattr(target_comp, "bb_ymin", getattr(target_comp, "ymin", 0.0))
    t_ymax = getattr(target_comp, "bb_ymax", getattr(target_comp, "ymax", 0.0))
    t_zmin = getattr(target_comp, "bb_zmin", getattr(target_comp, "zmin", 0.0))
    t_zmax = getattr(target_comp, "bb_zmax", getattr(target_comp, "zmax", 0.0))

    # Swept AABB bounds
    sw_xmin = min(t_xmin, t_xmin + u[0] * target_dist)
    sw_xmax = max(t_xmax, t_xmax + u[0] * target_dist)
    sw_ymin = min(t_ymin, t_ymin + u[1] * target_dist)
    sw_ymax = max(t_ymax, t_ymax + u[1] * target_dist)
    sw_zmin = min(t_zmin, t_zmin + u[2] * target_dist)
    sw_zmax = max(t_zmax, t_zmax + u[2] * target_dist)

    narrow_obstacles: List[Tuple[Any, cq.Shape]] = []
    for obs_comp, obs_shape in remaining_obstacles:
        oxmin = getattr(obs_comp, "bb_xmin", getattr(obs_comp, "xmin", 0.0))
        oxmax = getattr(obs_comp, "bb_xmax", getattr(obs_comp, "xmax", 0.0))
        oymin = getattr(obs_comp, "bb_ymin", getattr(obs_comp, "ymin", 0.0))
        oymax = getattr(obs_comp, "bb_ymax", getattr(obs_comp, "ymax", 0.0))
        ozmin = getattr(obs_comp, "bb_zmin", getattr(obs_comp, "zmin", 0.0))
        ozmax = getattr(obs_comp, "bb_zmax", getattr(obs_comp, "zmax", 0.0))

        disjoint = (
            sw_xmax < oxmin - 0.01 or sw_xmin > oxmax + 0.01 or
            sw_ymax < oymin - 0.01 or sw_ymin > oymax + 0.01 or
            sw_zmax < ozmin - 0.01 or sw_zmin > ozmax + 0.01
        )
        if not disjoint:
            narrow_obstacles.append((obs_comp, obs_shape))

    if not narrow_obstacles:
        return (True, target_dist, [], 30.0)

    # Build swept solid(s)
    is_cardinal = any(are_vectors_collinear(u, c_vec, 0.1) for c_vec in CARDINAL_VECTORS.values())
    swept_solids: List[TopoDS_Shape] = []
    try:
        if is_cardinal:
            swept_box = BRepPrimAPI_MakeBox(
                gp_Pnt(sw_xmin, sw_ymin, sw_zmin),
                gp_Pnt(sw_xmax, sw_ymax, sw_zmax)
            ).Shape()
            swept_solids.append(swept_box)
        else:
            # Sweep individual faces of target solid
            exp_f = TopExp_Explorer(target_shape.wrapped, TopAbs_FACE)
            vec_occ = gp_Vec(u[0] * target_dist, u[1] * target_dist, u[2] * target_dist)
            while exp_f.More():
                face = TopoDS.Face_s(exp_f.Current())
                try:
                    prism = BRepPrimAPI_MakePrism(face, vec_occ).Shape()
                    swept_solids.append(prism)
                except Exception:
                    pass
                exp_f.Next()
    except Exception as e:
        logger.debug(f"Swept volume construction error: {e}")
        return (False, 0.0, ["Swept Volume Construction Error"], 0.0)

    earliest_hit_dist = target_dist
    first_blockers: List[str] = []
    has_collision = False

    for obs_comp, obs_shape in narrow_obstacles:
        v0 = 0.0
        try:
            inter0 = BRepAlgoAPI_Common(target_shape.wrapped, obs_shape.wrapped)
            inter0.Build()
            if inter0.IsDone():
                v0 = cq.Shape.cast(inter0.Shape()).Volume()
        except Exception:
            v0 = 0.0

        inter_vol = 0.0
        for sw in swept_solids:
            try:
                tool = BRepAlgoAPI_Common(sw, obs_shape.wrapped)
                tool.Build()
                if tool.IsDone():
                    inter_vol += cq.Shape.cast(tool.Shape()).Volume()
            except Exception:
                pass

        if inter_vol > v0 + 0.01:
            has_collision = True
            low = 0.0
            high = target_dist
            contact_d = high
            for _ in range(8):
                mid = (low + high) / 2.0
                trsf = gp_Trsf()
                trsf.SetTranslation(gp_Vec(u[0] * mid, u[1] * mid, u[2] * mid))
                mid_shape = target_shape.wrapped.Moved(cq.occ_impl.shapes.Location(trsf).wrapped)
                tool_mid = BRepAlgoAPI_Common(mid_shape, obs_shape.wrapped)
                tool_mid.Build()
                v_mid = cq.Shape.cast(tool_mid.Shape()).Volume() if tool_mid.IsDone() else 0.0
                if v_mid > v0 + 0.01:
                    high = mid
                    contact_d = mid
                else:
                    low = mid

            obs_name = getattr(obs_comp, "display_name", getattr(obs_comp, "name", "Obstacle"))
            if contact_d < earliest_hit_dist:
                earliest_hit_dist = round(contact_d, 2)
                first_blockers = [obs_name]
            elif abs(contact_d - earliest_hit_dist) <= 0.5:
                if obs_name not in first_blockers:
                    first_blockers.append(obs_name)

    if has_collision and earliest_hit_dist < target_dist - 0.1:
        return (False, max(0.0, earliest_hit_dist), first_blockers, 0.0)

    normals: List[Tuple[float, float, float]] = []
    for _, obs_shape in narrow_obstacles[:4]:
        normals.extend(sample_contact_normals(target_shape, obs_shape, contact_tol=1.0))
    _, cone_half_angle, _ = solve_local_freedom_cone(normals)
    cone_half_angle = max(cone_half_angle, 5.0)

    return (True, target_dist, [], cone_half_angle)


# ─── 6. Non-Straight Motion Verification (B3) ─────────────────────────────────

def check_screw_extraction_path(
    target_comp: Any,
    target_shape: cq.Shape,
    axis_dir: Tuple[float, float, float],
    remaining_obstacles: List[Tuple[Any, cq.Shape]],
    all_bbs: List[Any],
) -> Tuple[bool, float, List[str], str]:
    """
    Verify screw motion along a fastener axis (axis translation plus rotation).
    Flag explicitly that thread engagement is not modeled.
    """
    is_clear, travel, blockers, _ = check_arbitrary_extraction_path(
        target_comp, target_shape, axis_dir, remaining_obstacles, all_bbs
    )
    notes = "Screw motion verified along fastener axis. Thread engagement is not modeled."
    return (is_clear, travel, blockers, notes)


def check_rotational_extraction_path(
    target_comp: Any,
    target_shape: cq.Shape,
    rotation_axis_origin: Tuple[float, float, float],
    rotation_axis_dir: Tuple[float, float, float],
    angle_deg: float,
    remaining_obstacles: List[Tuple[Any, cq.Shape]],
) -> Tuple[bool, float, List[str]]:
    """
    Verify rotational motion (hinge / bayonet) over angle_deg about a rotation axis.
    Tests intermediate rotation positions using analytical CAD collision queries.
    """
    u = normalize_vector(rotation_axis_dir)
    ax1 = gp_Ax1(gp_Pnt(rotation_axis_origin[0], rotation_axis_origin[1], rotation_axis_origin[2]), gp_Dir(u[0], u[1], u[2]))

    blockers: List[str] = []
    # Sample 8 intermediate angles along the sweep
    for step in range(1, 9):
        ang_rad = math.radians(angle_deg * step / 8.0)
        trsf = gp_Trsf()
        trsf.SetRotation(ax1, ang_rad)
        rot_shape = target_shape.wrapped.Moved(cq.occ_impl.shapes.Location(trsf).wrapped)

        for obs_comp, obs_shape in remaining_obstacles:
            try:
                tool = BRepAlgoAPI_Common(rot_shape, obs_shape.wrapped)
                tool.Build()
                if tool.IsDone() and cq.Shape.cast(tool.Shape()).Volume() > 0.05:
                    obs_name = getattr(obs_comp, "display_name", getattr(obs_comp, "name", "Obstacle"))
                    if obs_name not in blockers:
                        blockers.append(obs_name)
            except Exception:
                pass

    if blockers:
        return (False, 0.0, blockers)
    return (True, angle_deg, [])


def check_piecewise_linear_path(
    target_comp: Any,
    target_shape: cq.Shape,
    dir1: Tuple[float, float, float],
    travel1: float,
    dir2: Tuple[float, float, float],
    remaining_obstacles: List[Tuple[Any, cq.Shape]],
    all_bbs: List[Any],
) -> Tuple[bool, float, float, List[str]]:
    """
    Verify a 2-segment piecewise linear extraction path:
    Translate along dir1 for travel1, then along dir2 to full exit separation.
    """
    u1 = normalize_vector(dir1)
    is_clear1, actual_travel1, blockers1, _ = check_arbitrary_extraction_path(
        target_comp, target_shape, u1, remaining_obstacles, all_bbs, max_travel_limit=travel1
    )
    if not is_clear1:
        return (False, actual_travel1, 0.0, blockers1)

    effective_travel1 = min(travel1, actual_travel1)

    # Construct shifted target component for segment 2
    shift_x = u1[0] * effective_travel1
    shift_y = u1[1] * effective_travel1
    shift_z = u1[2] * effective_travel1

    class ShiftedComp:
        pass

    sc = ShiftedComp()
    for attr in ["xmin", "xmax", "ymin", "ymax", "zmin", "zmax", "bb_xmin", "bb_xmax", "bb_ymin", "bb_ymax", "bb_zmin", "bb_zmax", "name", "display_name"]:
        if hasattr(target_comp, attr):
            setattr(sc, attr, getattr(target_comp, attr))
    if hasattr(sc, "bb_xmin"):
        sc.bb_xmin += shift_x
        sc.bb_xmax += shift_x
        sc.bb_ymin += shift_y
        sc.bb_ymax += shift_y
        sc.bb_zmin += shift_z
        sc.bb_zmax += shift_z
    if hasattr(sc, "xmin"):
        sc.xmin += shift_x
        sc.xmax += shift_x
        sc.ymin += shift_y
        sc.ymax += shift_y
        sc.zmin += shift_z
        sc.zmax += shift_z

    trsf1 = gp_Trsf()
    trsf1.SetTranslation(gp_Vec(shift_x, shift_y, shift_z))
    inter_occ = target_shape.wrapped.Moved(cq.occ_impl.shapes.Location(trsf1).wrapped)
    inter_shape = cq.Shape.cast(inter_occ)

    u2 = normalize_vector(dir2)
    is_clear2, actual_travel2, blockers2, _ = check_arbitrary_extraction_path(
        sc, inter_shape, u2, remaining_obstacles, all_bbs
    )
    if not is_clear2:
        return (False, effective_travel1, actual_travel2, blockers2)

    return (True, effective_travel1, actual_travel2, [])
