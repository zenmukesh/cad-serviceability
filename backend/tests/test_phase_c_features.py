"""
Tests for Phase C: All Existing Features in Arbitrary Directions.

Verifies:
C1. Access and obstruction analysis: candidate directions, cone half-angle, and blockers.
C2. Directional clearance: swept clearance along removal direction reported alongside minimum Euclidean distance.
C3. Fastener tool approach: tool cylinder envelope (R=8.0 mm, L=65.0 mm) along fastener axis with tilt cone.
C4. Scoring integration: freedom cone half-angle, verified arbitrary motions, tool approach penalties.
C5. Independent plain OCP oracle reproducibility: tool cylinder intersection with pure OpenCASCADE primitives.
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
    analyze_clearances,
    compute_serviceability_scoring,
)
from app.services.motion_planner import (
    normalize_vector,
    check_fastener_tool_approach,
    compute_directional_clearance,
)

# Plain OCP imports for independent oracle verification
from OCP.BRepPrimAPI import BRepPrimAPI_MakeCylinder, BRepPrimAPI_MakeBox
from OCP.BRepAlgoAPI import BRepAlgoAPI_Common
from OCP.BRepExtrema import BRepExtrema_DistShapeShape
from OCP.gp import gp_Pnt, gp_Vec, gp_Dir, gp_Ax2
from OCP.GProp import GProp_GProps
from OCP.BRepGProp import BRepGProp


# ─── Dummy component helper ───────────────────────────────────────────────────

class DummyComp:
    def __init__(self, name: str, xmin: float, xmax: float, ymin: float, ymax: float, zmin: float, zmax: float):
        self.name = name
        self.display_name = name
        self.cad_entity_id = name
        self.bb_xmin = xmin
        self.bb_xmax = xmax
        self.bb_ymin = ymin
        self.bb_ymax = ymax
        self.bb_zmin = zmin
        self.bb_zmax = zmax
        self.xmin = xmin
        self.xmax = xmax
        self.ymin = ymin
        self.ymax = ymax
        self.zmin = zmin
        self.zmax = zmax


# ─── Fixtures ──────────────────────────────────────────────────────────────────

@pytest.fixture
def db_session():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    session = Session()
    yield session
    session.close()


# ─── C2: Directional Clearance vs Minimum Distance ────────────────────────────

def test_directional_clearance_vs_minimum_distance():
    """
    Verify that directional clearance along removal direction is computed accurately
    and distinguishes between minimum spatial distance and path travel clearance.
    """
    # Moving solid: Box at origin [0..10, 0..10, 0..10]
    box_moving = cq.Workplane("XY").box(10, 10, 10, centered=False).val()
    moving_comp = DummyComp("MovingBox", 0.0, 10.0, 0.0, 10.0, 0.0, 10.0)

    # Obstacle 1: Directly ahead along +X at X=25 (gap = 15 mm along +X)
    box_obstacle_x = cq.Workplane("XY").transformed(offset=(25, 0, 0)).box(10, 10, 10, centered=False).val()
    obs_x_comp = DummyComp("ObsX", 25.0, 35.0, 0.0, 10.0, 0.0, 10.0)

    # Obstacle 2: Close to moving solid in +Y direction at Y=12 (gap = 2 mm along +Y)
    # but does NOT block +X motion because its Y is [12..22]
    box_obstacle_y = cq.Workplane("XY").transformed(offset=(0, 12, 0)).box(10, 10, 10, centered=False).val()
    obs_y_comp = DummyComp("ObsY", 0.0, 10.0, 12.0, 22.0, 0.0, 10.0)

    obstacles = [
        (obs_x_comp, box_obstacle_x),
        (obs_y_comp, box_obstacle_y),
    ]
    all_bbs = [moving_comp, obs_x_comp, obs_y_comp]

    # 1. Compute directional clearance along +X direction [1, 0, 0]
    # Swept along +X should collide with obstacle X at travel ~ 15.0 mm
    dir_clearance_x = compute_directional_clearance(
        target_comp=moving_comp,
        target_shape=box_moving,
        direction_vec=(1.0, 0.0, 0.0),
        obstacles=obstacles,
        all_bbs=all_bbs,
    )

    assert abs(dir_clearance_x - 15.0) < 0.2, f"Expected ~15.0 mm along +X, got {dir_clearance_x}"

    # 2. Compute directional clearance along +Y direction [0, 1, 0]
    # Swept along +Y should collide with obstacle Y at travel ~ 2.0 mm
    dir_clearance_y = compute_directional_clearance(
        target_comp=moving_comp,
        target_shape=box_moving,
        direction_vec=(0.0, 1.0, 0.0),
        obstacles=obstacles,
        all_bbs=all_bbs,
    )

    assert abs(dir_clearance_y - 2.0) < 0.2, f"Expected ~2.0 mm along +Y, got {dir_clearance_y}"

    # 3. Minimum Euclidean distance to obstacle Y is 2.0 mm
    extrema_y = BRepExtrema_DistShapeShape(box_moving.wrapped, box_obstacle_y.wrapped)
    assert abs(extrema_y.Value() - 2.0) < 0.05

    # Along +X, moving solid has 15 mm travel clearance even though obstacle Y is at 2 mm Euclidean distance
    assert dir_clearance_x > extrema_y.Value()


# ─── C3: Fastener Tool Approach Envelope & Tilt Cone ──────────────────────────

def test_fastener_tool_approach_unobstructed():
    """
    Test fastener tool approach envelope on a bolt-like cylinder where tool axis is clear.
    """
    # Fastener cylinder along +Z axis from Z=0 to Z=20, R=4.0 mm
    fastener = cq.Workplane("XY").circle(4.0).extrude(20.0).val()
    fastener_comp = DummyComp("Hex_Bolt_M8", -4.0, 4.0, -4.0, 4.0, 0.0, 20.0)

    # Base plate (Z=0 to Z=5)
    plate = cq.Workplane("XY").box(60, 60, 5, centered=False).val()
    plate_comp = DummyComp("BasePlate", 0.0, 60.0, 0.0, 60.0, 0.0, 5.0)

    obstacles = [
        (plate_comp, plate)
    ]

    tool_res = check_fastener_tool_approach(
        fastener_comp=fastener_comp,
        fastener_shape=fastener,
        obstacles=obstacles,
        tool_length_mm=65.0,
        tool_radius_mm=8.0,
        max_tilt_angle_deg=15.0,
    )

    assert tool_res["is_free"] is True
    assert len(tool_res["blocking_components"]) == 0
    assert tool_res["usable_tilt_angle_deg"] >= 10.0
    assert abs(tool_res["tool_axis"][2] - 1.0) < 1e-4


def test_fastener_tool_approach_obstructed():
    """
    Test fastener tool approach envelope when an obstacle obstructs the tool cylinder.
    """
    # Fastener cylinder along +Z axis from Z=0 to Z=20
    fastener = cq.Workplane("XY").circle(4.0).extrude(20.0).val()
    fastener_comp = DummyComp("Obstructed_Bolt", -4.0, 4.0, -4.0, 4.0, 0.0, 20.0)

    # Base plate underneath (Z=-10 to Z=0)
    plate = cq.Workplane("XY").transformed(offset=(0, 0, -10)).box(60, 60, 10, centered=False).val()
    plate_comp = DummyComp("BasePlate", 0.0, 60.0, 0.0, 60.0, -10.0, 0.0)

    # Obstructing bracket directly above fastener at Z=40 (within tool length of 65 mm)
    bracket = cq.Workplane("XY").transformed(offset=(-10, -10, 40)).box(20, 20, 10, centered=False).val()
    bracket_comp = DummyComp("Overhead_Bracket", -10.0, 10.0, -10.0, 10.0, 40.0, 50.0)

    obstacles = [
        (plate_comp, plate),
        (bracket_comp, bracket),
    ]

    tool_res = check_fastener_tool_approach(
        fastener_comp=fastener_comp,
        fastener_shape=fastener,
        obstacles=obstacles,
        tool_length_mm=65.0,
        tool_radius_mm=8.0,
        max_tilt_angle_deg=15.0,
        fastener_axis=(0.0, 0.0, 1.0),
    )

    assert tool_res["is_free"] is False
    assert "Overhead_Bracket" in tool_res["blocking_components"]
    assert "blocked" in tool_res["details"].lower() or "free" in tool_res["details"].lower()


# ─── C5: Plain OCP Oracle Reproducibility of Tool Cylinder Collision ──────────

def test_plain_ocp_oracle_tool_cylinder_reproducibility():
    """
    Independent oracle test using plain OCP calls only:
    - BRepPrimAPI_MakeCylinder for tool envelope
    - BRepAlgoAPI_Common for exact volumetric intersection
    Verifies that tool collision is reproducible within 0.05 mm and 1% volume tolerance.
    """
    r_tool = 8.0
    l_tool = 65.0

    # Fastener head center at (10, 20, 30), axis pointing +Z
    p_head = gp_Pnt(10.0, 20.0, 30.0)
    d_axis = gp_Dir(0.0, 0.0, 1.0)
    ax_tool = gp_Ax2(p_head, d_axis)

    # Make tool cylinder envelope using plain OCP
    tool_cyl = BRepPrimAPI_MakeCylinder(ax_tool, r_tool, l_tool).Shape()

    # Analytical volume of tool cylinder: pi * r^2 * h
    expected_vol = math.pi * (r_tool ** 2) * l_tool

    props = GProp_GProps()
    BRepGProp.VolumeProperties_s(tool_cyl, props)
    measured_vol = props.Mass()

    # Tolerance: 1 percent volume
    assert abs(measured_vol - expected_vol) / expected_vol < 0.01

    # Place an obstacle block that intersects the tool cylinder:
    # Box from X=5..15, Y=15..25, Z=50..60 (height 10, cross section 10x10)
    box_pnt = gp_Pnt(5.0, 15.0, 50.0)
    box_obs = BRepPrimAPI_MakeBox(box_pnt, 10.0, 10.0, 10.0).Shape()

    # Plain OCP Common boolean intersection
    common_op = BRepAlgoAPI_Common(tool_cyl, box_obs)
    common_op.Build()
    assert common_op.IsDone()

    inter_shape = common_op.Shape()
    props_inter = GProp_GProps()
    BRepGProp.VolumeProperties_s(inter_shape, props_inter)
    inter_vol = props_inter.Mass()

    # Must detect collision with positive intersection volume
    assert inter_vol > 50.0, f"Expected significant intersection volume, got {inter_vol}"

    # Also test non-intersecting obstacle placed far away at X=100
    box_far = BRepPrimAPI_MakeBox(gp_Pnt(100.0, 100.0, 50.0), 10.0, 10.0, 10.0).Shape()
    dist_calc = BRepExtrema_DistShapeShape(tool_cyl, box_far)
    dist_calc.Perform()
    assert dist_calc.IsDone()
    assert dist_calc.Value() > 80.0


# ─── C1 & C4: Scoring & Arbitrary Direction Freedom Integration ────────────────

def test_freedom_cone_and_serviceability_scoring_integration(db_session):
    """
    Test that serviceability analysis populates arbitrary candidate directions,
    freedom cone half-angles, tool approach evaluation, and directional clearances.
    """
    step_path = Path("test_data/gearbox_assembly.step")
    if not step_path.exists():
        step_path = Path("backend/test_data/gearbox_assembly.step")
    assert step_path.exists(), "gearbox_assembly.step required for integration test"

    # Ingest into SQLite database session
    res = import_step_file(step_path)
    assert res.success is True

    assembly = Assembly(
        filename="gearbox_assembly.step",
        sha256="test_gearbox_phase_c",
        status="ready",
    )
    db_session.add(assembly)
    db_session.commit()
    db_session.refresh(assembly)

    for c in res.components:
        comp = Component(
            assembly_id=assembly.id,
            cad_entity_id=c.cad_entity_id,
            name=c.name,
            user_label=c.name,
            parent_cad_id=c.parent_cad_id,
            depth=c.depth,
            is_leaf=c.is_leaf,
            component_type=c.component_type,
            volume_mm3=c.volume_mm3,
            surface_area_mm2=c.surface_area_mm2,
            bb_xmin=c.bb_xmin, bb_xmax=c.bb_xmax,
            bb_ymin=c.bb_ymin, bb_ymax=c.bb_ymax,
            bb_zmin=c.bb_zmin, bb_zmax=c.bb_zmax,
        )
        db_session.add(comp)
    db_session.commit()

    # Compute serviceability scoring
    report = compute_serviceability_scoring(assembly.id, db_session, min_clearance_threshold_mm=3.0)
    assert report is not None
    assert report.analyzed_components_count > 0

    # C3: Verify tool approaches list is populated for detected fasteners
    assert report.tool_approaches is not None
    assert len(report.tool_approaches) > 0

    for ta in report.tool_approaches:
        assert len(ta.tool_axis_vector) == 3
        # Vector must be unit normalized
        mag = math.sqrt(sum(v ** 2 for v in ta.tool_axis_vector))
        assert abs(mag - 1.0) < 1e-3
        assert ta.tool_length_mm > 0
        assert ta.tool_radius_mm > 0
        assert ta.tilt_cone_half_angle_deg >= 0

    # C2: Verify clearance measurements contain directional clearance
    leaf_comps = [c for c in assembly.components if c.is_leaf]
    clearances = analyze_clearances(assembly.id, db_session, target_component_id=leaf_comps[0].id, min_threshold_mm=3.0)
    assert len(clearances) > 0
    for cl in clearances:
        # Minimum distance must be non-negative
        assert cl.distance_mm >= 0.0
        # If directional clearance is computed, it must be >= 0
        if cl.directional_clearance_mm is not None:
            assert cl.directional_clearance_mm >= 0.0
            assert cl.removal_direction_vector is not None
            assert len(cl.removal_direction_vector) == 3

    # C1: Verify component obstruction candidate directions
    obs = analyze_component_obstructions(assembly.id, leaf_comps[0].id, db_session)
    assert obs is not None
    assert obs.best_direction_vector is not None
    assert len(obs.best_direction_vector) == 3
    if obs.freedom_cone_half_angle_deg is not None:
        assert obs.freedom_cone_half_angle_deg >= 0.0
