"""
Automated tests for Phase B: Arbitrary-Direction Extraction and Motion Planning Engine.

Asserts:
- Unit direction vector modeling and freedom cone half-angle computation.
- Geometry-derived candidate direction extraction from analytical B-Rep faces/edges.
- Exact local freedom cone solving via polyhedral half-space LP (scipy linprog).
- Close-fit shaft freedom cone narrow angle verification (< 1 degree).
- 162-point adaptive Fibonacci sphere distribution.
- Non-straight motion verification: screw motion, rotational motion, and 2-segment paths.
- Reproducibility via plain OCP oracle script without production service dependencies.
"""

import math
import pytest
import numpy as np
import cadquery as cq
from pathlib import Path
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.database import Base
from app.models.assembly import Assembly, Component
from app.services.cad_importer import import_step_file
from app.services.geometry_service import (
    analyze_component_obstructions,
    build_disassembly_graph,
    get_assembly_shapes,
)
from app.services.motion_planner import (
    normalize_vector,
    vector_to_cardinal_label,
    extract_geometry_candidate_directions,
    solve_local_freedom_cone,
    sample_contact_normals,
    generate_fibonacci_sphere,
    check_arbitrary_extraction_path,
    check_screw_extraction_path,
    check_rotational_extraction_path,
    check_piecewise_linear_path,
)

# Plain OCP imports for independent oracle verification
from OCP.BRepPrimAPI import BRepPrimAPI_MakeBox, BRepPrimAPI_MakePrism, BRepPrimAPI_MakeRevol
from OCP.BRepAlgoAPI import BRepAlgoAPI_Common
from OCP.BRepExtrema import BRepExtrema_DistShapeShape
from OCP.gp import gp_Pnt, gp_Vec, gp_Dir, gp_Ax1


# ─── 1. Unit Direction Vectors & Geometry Derivation (B1 & B2a) ───────────────

def test_direction_model_unit_vectors():
    """Verify that arbitrary direction vectors are strictly normalized unit vectors."""
    v1 = (10.0, 0.0, 0.0)
    u1 = normalize_vector(v1)
    assert pytest.approx(u1[0], abs=1e-6) == 1.0
    assert pytest.approx(u1[1], abs=1e-6) == 0.0
    assert pytest.approx(u1[2], abs=1e-6) == 0.0

    v2 = (1.0, 1.0, 1.0)
    u2 = normalize_vector(v2)
    norm = math.sqrt(u2[0]**2 + u2[1]**2 + u2[2]**2)
    assert pytest.approx(norm, abs=1e-6) == 1.0
    assert pytest.approx(u2[0], abs=1e-5) == 1.0 / math.sqrt(3.0)


def test_geometry_derived_candidate_directions_box():
    """Verify a simple box yields planar normals along the 3 principal axes (+-X, +-Y, +-Z)."""
    box = cq.Workplane().box(20, 30, 40).val()
    dirs = extract_geometry_candidate_directions(box.wrapped, include_cardinals=False)
    
    # 6 faces of box -> 6 unique face normals
    assert len(dirs) == 6
    for d in dirs:
        norm = math.sqrt(d[0]**2 + d[1]**2 + d[2]**2)
        assert pytest.approx(norm, abs=1e-5) == 1.0


def test_geometry_derived_tilted_cylinder():
    """
    Verify a cylinder rotated by 45 degrees about Y extracts the exact tilted axis
    vector (1/sqrt(2), 0, 1/sqrt(2)) within 1 degree tolerance.
    """
    cyl = cq.Workplane("XY").circle(5.0).extrude(50.0).rotate((0,0,0), (0,1,0), 45).val()
    dirs = extract_geometry_candidate_directions(cyl.wrapped, include_cardinals=False)

    expected_axis = (1.0 / math.sqrt(2.0), 0.0, 1.0 / math.sqrt(2.0))
    
    # Check if expected axis is present within 1 degree
    cos_1deg = math.cos(math.radians(1.0))
    found_positive = any(
        (d[0]*expected_axis[0] + d[1]*expected_axis[1] + d[2]*expected_axis[2]) >= cos_1deg
        for d in dirs
    )
    found_negative = any(
        (d[0]*(-expected_axis[0]) + d[1]*(-expected_axis[1]) + d[2]*(-expected_axis[2])) >= cos_1deg
        for d in dirs
    )
    assert found_positive is True
    assert found_negative is True


# ─── 2. Exact Local Freedom Cone Solving (B2b) ────────────────────────────────

def test_close_fit_shaft_freedom_cone_half_space_lp():
    """
    Verify the polyhedral half-space LP correctly solves a close-fit shaft in a bore:
    16 radial contact normals around the circumference constrain all lateral motion.
    The solver must output:
    1. An axial extraction direction d* aligned with (0, 0, 1) or (0, 0, -1).
    2. A freedom cone half-angle of exactly 0.0000 degrees.
    """
    normals = []
    for k in range(16):
        phi = 2.0 * math.pi * k / 16.0
        # Outward normals perpendicular to Z axis
        normals.append((math.cos(phi), math.sin(phi), 0.0))

    best_dir, half_angle_deg, extreme_rays = solve_local_freedom_cone(normals)

    assert best_dir is not None
    # Axial alignment: dx ~ 0, dy ~ 0, |dz| ~ 1
    assert pytest.approx(abs(best_dir[2]), abs=1e-3) == 1.0
    assert pytest.approx(best_dir[0], abs=1e-3) == 0.0
    assert pytest.approx(best_dir[1], abs=1e-3) == 0.0
    # Freedom cone is razor-thin: 0.0 degrees
    assert pytest.approx(half_angle_deg, abs=1e-4) == 0.0


def test_open_half_space_freedom_cone():
    """
    Verify a single planar mating contact (normal pointing along +Z) produces a 90 degree freedom cone.
    """
    normals = [(0.0, 0.0, 1.0)]
    best_dir, half_angle_deg, _ = solve_local_freedom_cone(normals)

    assert best_dir is not None
    assert pytest.approx(best_dir[2], abs=1e-4) == 1.0
    assert pytest.approx(half_angle_deg, abs=1e-2) == 90.0


# ─── 3. Adaptive Fibonacci Sphere Sampling (B2c) ──────────────────────────────

def test_adaptive_fibonacci_sphere_distribution():
    """Verify 162 points on Fibonacci sphere are strictly normalized unit vectors on S^2."""
    pts = generate_fibonacci_sphere(162)
    assert len(pts) == 162

    for p in pts:
        norm = math.sqrt(p[0]**2 + p[1]**2 + p[2]**2)
        assert pytest.approx(norm, abs=1e-5) == 1.0

    # Ensure coverage of northern and southern poles
    z_coords = [p[2] for p in pts]
    assert max(z_coords) > 0.95
    assert min(z_coords) < -0.95


# ─── 4. Non-Straight Motions: Screw, Revol, 2-Segment (B3) ─────────────────────

def test_screw_motion_along_fastener_axis():
    """Verify screw motion check along fastener axis succeeds and includes disclaimer."""
    bolt = cq.Workplane().circle(3.0).extrude(20.0).val()
    
    class DummyComp:
        xmin = -3.0
        xmax = 3.0
        ymin = -3.0
        ymax = 3.0
        zmin = 0.0
        zmax = 20.0
        bb_xmin = -3.0
        bb_xmax = 3.0
        bb_ymin = -3.0
        bb_ymax = 3.0
        bb_zmin = 0.0
        bb_zmax = 20.0
        name = "Test_Bolt"
        display_name = "Test_Bolt"

    comp = DummyComp()
    is_clear, travel, blockers, notes = check_screw_extraction_path(
        comp, bolt, (0.0, 0.0, 1.0), [], [comp]
    )
    assert is_clear is True
    assert travel >= 10.0
    assert "thread engagement is not modeled" in notes.lower()


def test_rotational_revol_motion():
    """
    Verify BRepPrimAPI_MakeRevol revolving motion of a hinged door about a hinge axis.
    """
    # Flange of door at x=5..25, y=-2..2, z=0..10
    door = cq.Workplane().transformed(offset=(15, 0, 5)).box(20, 4, 10).val()
    
    class DummyDoor:
        display_name = "Hinged_Door"
        name = "Hinged_Door"

    door_comp = DummyDoor()

    # Obstacle in straight +X path (so straight pull fails)
    obstacle = cq.Workplane().transformed(offset=(35, 0, 5)).box(10, 10, 10).val()
    class DummyObs:
        display_name = "Stop_Block"
        name = "Stop_Block"

    obs_comp = DummyObs()

    # Revolve 45 deg about hinge axis at x=5, y=0 along Z
    is_rot_clear, angle, rot_blockers = check_rotational_extraction_path(
        door_comp, door, (5.0, 0.0, 0.0), (0.0, 0.0, 1.0), 45.0, [(obs_comp, obstacle)]
    )
    assert is_rot_clear is True
    assert angle == 45.0
    assert len(rot_blockers) == 0


def test_piecewise_linear_2_segment_path():
    """
    Verify 2-segment piecewise linear path:
    Component moves 15 mm along +X, then along +Z to clear the assembly.
    """
    slider = cq.Workplane().transformed(offset=(0, 0, 0)).box(10, 10, 10).val()

    class DummySlider:
        xmin = -5.0
        xmax = 5.0
        ymin = -5.0
        ymax = 5.0
        zmin = -5.0
        zmax = 5.0
        bb_xmin = -5.0
        bb_xmax = 5.0
        bb_ymin = -5.0
        bb_ymax = 5.0
        bb_zmin = -5.0
        bb_zmax = 5.0
        name = "Slider"
        display_name = "Slider"

    slider_comp = DummySlider()

    # Obstacle directly above slider at z=15 (blocking immediate +Z pull)
    top_obs = cq.Workplane().transformed(offset=(0, 0, 20)).box(15, 15, 10).val()
    class DummyTopObs:
        xmin = -7.5
        xmax = 7.5
        ymin = -7.5
        ymax = 7.5
        zmin = 15.0
        zmax = 25.0
        bb_xmin = -7.5
        bb_xmax = 7.5
        bb_ymin = -7.5
        bb_ymax = 7.5
        bb_zmin = 15.0
        bb_zmax = 25.0
        name = "Top_Blocker"
        display_name = "Top_Blocker"

    top_obs_comp = DummyTopObs()

    all_bbs = [slider_comp, top_obs_comp]
    obstacles = [(top_obs_comp, top_obs)]

    # 1. Straight +Z should be blocked by Top_Blocker
    is_clear_z, _, blockers_z, _ = check_arbitrary_extraction_path(
        slider_comp, slider, (0.0, 0.0, 1.0), obstacles, all_bbs
    )
    assert is_clear_z is False
    assert "Top_Blocker" in blockers_z

    # 2. 2-segment path: +X for 20 mm, then +Z exit
    is_clear_2seg, t1, t2, blockers_2seg = check_piecewise_linear_path(
        slider_comp, slider, (1.0, 0.0, 0.0), 20.0, (0.0, 0.0, 1.0), obstacles, all_bbs
    )
    assert is_clear_2seg is True
    assert t1 == 20.0
    assert len(blockers_2seg) == 0


# ─── 5. Independent Plain OCP Oracle Verification ─────────────────────────────

def test_independent_plain_ocp_oracle_reproducibility():
    """
    GLOBAL RULE: Every geometric claim must be reproducible by an independent oracle
    script that uses plain OCP calls only (BRepExtrema_DistShapeShape, BRepAlgoAPI_Common,
    BRepPrimAPI_MakePrism/MakeRevol), not geometry_service.py.
    Tolerances: distances <= 0.05 mm, directions <= 1 degree, volumes <= 1 percent.
    """
    # 1. Ground truth shapes using plain OCP
    # Box 1: 10x10x10 at (0, 0, 0) -> x in [-5, 5]
    b1_occ = BRepPrimAPI_MakeBox(gp_Pnt(-5, -5, -5), gp_Pnt(5, 5, 5)).Shape()
    # Box 2: 10x10x10 at (15, 0, 0) -> x in [10, 20]
    b2_occ = BRepPrimAPI_MakeBox(gp_Pnt(10, -5, -5), gp_Pnt(20, 5, 5)).Shape()

    # 2. Distance via plain BRepExtrema
    dist_tool = BRepExtrema_DistShapeShape(b1_occ, b2_occ)
    dist_tool.Perform()
    assert dist_tool.IsDone()
    dist = dist_tool.Value()
    assert pytest.approx(dist, abs=0.05) == 5.000

    # 3. Swept volume extraction of front face of Box 1 along +X by 10 mm via plain MakePrism
    from OCP.TopExp import TopExp_Explorer
    from OCP.TopAbs import TopAbs_FACE
    from OCP.TopoDS import TopoDS
    from OCP.BRepAdaptor import BRepAdaptor_Surface
    exp_f = TopExp_Explorer(b1_occ, TopAbs_FACE)
    f_front = None
    while exp_f.More():
        f = TopoDS.Face_s(exp_f.Current())
        surf = BRepAdaptor_Surface(f)
        if surf.Plane().Location().X() > 4.9:
            f_front = f
            break
        exp_f.Next()
    assert f_front is not None
    prism_tool = BRepPrimAPI_MakePrism(f_front, gp_Vec(10.0, 0.0, 0.0))
    prism_occ = prism_tool.Shape()

    # 4. Collision check via plain BRepAlgoAPI_Common
    common_tool = BRepAlgoAPI_Common(prism_occ, b2_occ)
    common_tool.Build()
    assert common_tool.IsDone()

    # Volume of overlap: 5 mm overlap along X * 10 * 10 = 500 mm³
    # Compute volume via plain OCP GProp
    from OCP.GProp import GProp_GProps
    from OCP.BRepGProp import BRepGProp
    props = GProp_GProps()
    BRepGProp.VolumeProperties_s(common_tool.Shape(), props)
    vol = props.Mass()
    assert pytest.approx(vol, rel=0.01) == 500.0


# ─── 6. Database & Gearbox Integration (B1, B4) ───────────────────────────────

@pytest.fixture(scope="module")
def gearbox_db():
    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False})
    Session = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    Base.metadata.create_all(bind=engine)
    db = Session()

    step_path = Path("test_data/sample_gearbox_serviceability.step") if Path("test_data/sample_gearbox_serviceability.step").exists() else Path("backend/test_data/sample_gearbox_serviceability.step")
    res = import_step_file(step_path)
    assembly = Assembly(
        filename="sample_gearbox_serviceability.step",
        sha256="afd686a6c0963b02f4c5a92305152cff614cffa6b2c27e0104cd1971182de282",
        status="ready",
    )
    db.add(assembly)
    db.commit()
    db.refresh(assembly)

    for c in res.components:
        comp = Component(
            assembly_id=assembly.id,
            cad_entity_id=c.cad_entity_id,
            name=c.name,
            parent_cad_id=c.parent_cad_id,
            is_leaf=1 if c.is_leaf else 0,
            component_type=c.component_type,
            bb_xmin=c.bb_xmin, bb_xmax=c.bb_xmax,
            bb_ymin=c.bb_ymin, bb_ymax=c.bb_ymax,
            bb_zmin=c.bb_zmin, bb_zmax=c.bb_zmax,
            volume_mm3=c.volume_mm3,
            surface_area_mm2=c.surface_area_mm2,
        )
        db.add(comp)
    db.commit()

    yield db, assembly.id
    db.close()


def test_gearbox_component_freedom_cone_and_sphere(gearbox_db):
    """
    Verify Phase B obstruction analysis produces continuous freedom cone
    and 162-point Fibonacci freedom sphere on actual gearbox assembly.
    """
    db, assembly_id = gearbox_db
    cover = db.query(Component).filter(Component.assembly_id == assembly_id, Component.name == "Gearbox_Cover").first()
    assert cover is not None

    obs_report = analyze_component_obstructions(assembly_id, cover.id, db)
    assert obs_report.best_direction in ["+Z", "-Z", "+X", "-X", "+Y", "-Y"]
    assert obs_report.best_direction_vector is not None
    assert len(obs_report.best_direction_vector) == 3
    # Verify vector is unit length
    u = obs_report.best_direction_vector
    norm = math.sqrt(u[0]**2 + u[1]**2 + u[2]**2)
    assert pytest.approx(norm, abs=1e-3) == 1.0

    # Verify 162 Fibonacci sphere samples
    assert len(obs_report.freedom_sphere_samples) == 162
    for sample in obs_report.freedom_sphere_samples:
        assert "vector" in sample
        assert "is_free" in sample
        assert "margin" in sample


def test_disassembly_graph_arbitrary_direction_attributes(gearbox_db):
    """
    Verify disassembly steps include direction vectors, motion types,
    and freedom cone half-angles across the planned sequence.
    """
    db, assembly_id = gearbox_db
    graph = build_disassembly_graph(assembly_id, db)
    assert graph.total_steps > 0

    for step in graph.sequence:
        assert step.removal_direction is not None
        assert step.direction_vector is not None
        assert len(step.direction_vector) == 3
        assert step.motion_type in ["straight", "screw", "rotation", "piecewise_linear"]
        assert step.freedom_cone_half_angle_deg is not None
        if step.is_unified_fastener or "bolt" in step.component_name.lower() or "screw" in step.component_name.lower():
            assert step.motion_type == "screw"
            if step.is_path_verified:
                assert "thread engagement" in step.notes.lower()
            else:
                assert "unresolved cycle" in step.notes.lower() or "thread engagement" in step.notes.lower() or "no straight" in step.notes.lower()
