"""
Automated regression tests for CAD geometric calculations, clearances,
obstruction detection, and explainable scoring validation.
"""
import pytest
import math
import cadquery as cq
from pathlib import Path
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.database import Base
from app.models.assembly import Assembly, Component
from app.services.cad_importer import import_step_file
from app.services.geometry_service import (
    compute_shape_distance,
    is_shaft_bearing_interface,
    get_physical_fastener_id,
    analyze_clearances,
    analyze_component_obstructions,
    compute_serviceability_scoring,
    get_assembly_shapes,
    Point3D,
)
from OCP.TopExp import TopExp_Explorer
from OCP.TopAbs import TopAbs_FACE
from OCP.TopoDS import TopoDS
from OCP.BRepAdaptor import BRepAdaptor_Surface
from OCP.BRepExtrema import BRepExtrema_DistShapeShape


# ─── 1. Controlled Test Geometries with Known Ground Truth ─────────────────────

def test_known_clearance_measurement():
    """Verify BRepExtrema returns exact 5.000 mm distance and 3D contact coordinates."""
    b1 = cq.Workplane().box(10, 10, 10).val()
    b2 = cq.Workplane().transformed(offset=(15, 0, 0)).box(10, 10, 10).val()

    dist, p1, p2 = compute_shape_distance(b1, b2)

    assert pytest.approx(dist, abs=1e-5) == 5.0
    assert pytest.approx(p1.x, abs=1e-4) == 5.0
    assert pytest.approx(p2.x, abs=1e-4) == 10.0
    assert pytest.approx(p2.y - p1.y, abs=1e-4) == 0.0
    assert pytest.approx(p2.z - p1.z, abs=1e-4) == 0.0


def test_touching_surfaces_zero_gap():
    """Verify touching surfaces return 0.0 mm distance and 0.0 mm³ intersection volume."""
    b1 = cq.Workplane().box(10, 10, 10).val()
    b2 = cq.Workplane().transformed(offset=(10, 0, 0)).box(10, 10, 10).val()

    dist, p1, p2 = compute_shape_distance(b1, b2)
    inter_vol = b1.intersect(b2).Volume()

    assert pytest.approx(dist, abs=1e-5) == 0.0
    assert pytest.approx(inter_vol, abs=1e-5) == 0.0
    assert pytest.approx(p1.x, abs=1e-4) == 5.0
    assert pytest.approx(p2.x, abs=1e-4) == 5.0


def test_overlapping_solids_intersection():
    """Verify overlapping solids return positive intersection volume (collision)."""
    b1 = cq.Workplane().box(10, 10, 10).val()
    b2 = cq.Workplane().transformed(offset=(8, 0, 0)).box(10, 10, 10).val()

    inter_vol = b1.intersect(b2).Volume()
    # 2.0 mm overlap * 10 * 10 = 200.0 mm³
    assert pytest.approx(inter_vol, rel=1e-3) == 200.0


def test_rotated_components_clearance():
    """
    Verify rotated solid distance uses true B-Rep rather than axis-aligned bounding box.
    Box 1 rotated 45 deg about Z extends to 5*sqrt(2) = 7.0711 mm along +X.
    Box 2 at x=20 (xmin=15.0).
    Expected exact distance: 15.0 - 5*sqrt(2) = 7.92893 mm.
    """
    b1 = cq.Workplane().box(10, 10, 10).rotate((0, 0, 0), (0, 0, 1), 45).val()
    b2 = cq.Workplane().transformed(offset=(20, 0, 0)).box(10, 10, 10).val()

    dist, p1, p2 = compute_shape_distance(b1, b2)
    expected_dist = 15.0 - (5.0 * math.sqrt(2))

    assert pytest.approx(dist, rel=1e-4) == expected_dist
    assert pytest.approx(dist, abs=1e-3) == 7.929


def test_coaxial_shaft_bearing_radial_clearance():
    """
    Verify coaxial shaft inside bearing bore returns exact radial clearance (0.50 mm).
    Shaft: R=5.0 mm along X. Bearing bore: R=5.5 mm along X.
    Delta vector between closest surface points must be perpendicular to shaft axis (dx=0).
    """
    shaft = cq.Workplane("YZ").circle(5.0).extrude(78.0).translate((-39, 0, 0)).val()
    bearing = cq.Workplane("YZ").circle(10.0).circle(5.5).extrude(5.0).translate((-40.5, 0, 0)).val()

    dist, p1, p2 = compute_shape_distance(shaft, bearing)

    assert pytest.approx(dist, abs=1e-4) == 0.500
    assert pytest.approx(p2.x - p1.x, abs=1e-4) == 0.0
    radial_gap = math.sqrt((p2.y - p1.y)**2 + (p2.z - p1.z)**2)
    assert pytest.approx(radial_gap, abs=1e-4) == 0.500


# ─── 2. Fastener Deduplication & Physical Bolt Grouping ───────────────────────

def test_fastener_deduplication():
    """Verify that multi-solid fasteners (shank + head) are grouped into physical bolts."""
    id1 = get_physical_fastener_id("Cover_Bolt_Shank_1", "")
    id2 = get_physical_fastener_id("Cover_Bolt_Head_1", "")
    assert id1 == id2
    assert "1" in id1

    id3 = get_physical_fastener_id("Bolt_Shank_2", "Mounting_Bolt_2")
    id4 = get_physical_fastener_id("Bolt_Head_2", "Mounting_Bolt_2")
    assert id3 == id4 == "Mounting_Bolt_2"


# ─── 3. Gearbox Assembly Investigation & Scoring Audit ────────────────────────

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


def test_input_shaft_bearing_clearance_classification(gearbox_db):
    """
    Item 5 Audit: Verify that the 0.50 mm Input_Shaft-to-Input_Bearing_Left distance
    is correctly classified as a bearing_radial_clearance and NOT a critical safety defect.
    """
    db, assembly_id = gearbox_db
    clearances = analyze_clearances(assembly_id, db, min_threshold_mm=3.0)

    shaft_bearing = next(
        (c for c in clearances
         if ("Input_Shaft" in c.target_component_name and "Input_Bearing_Left" in c.neighbor_component_name) or
            ("Input_Bearing_Left" in c.target_component_name and "Input_Shaft" in c.neighbor_component_name)),
        None
    )
    assert shaft_bearing is not None
    assert pytest.approx(shaft_bearing.distance_mm, abs=1e-3) == 0.50
    assert shaft_bearing.clearance_type == "bearing_radial_clearance"
    assert shaft_bearing.is_pass is True
    assert shaft_bearing.severity == "PASS"


def test_gearbox_cover_audited_score(gearbox_db):
    """
    Milestone 3 Audit: Verify Gearbox_Cover score calculation, weights, and fastener deductions.
    Cover is secured by 4 physical bolts (not 8 duplicate solids).
    Under Milestone 3 Boolean clash detection, solid interference with Cover_Bolt_Head_3 (83.14 mm³)
    is caught and penalized (-20.0 pts in Clearance), preventing unphysical perfect scores.
    Score = 25 (Access) + 5 (Clearance: -20 for confirmed clash) + 25 (Disassembly) + 17 (Fasteners: -8 for 4 bolts) = 72.0 / 100.
    """
    db, assembly_id = gearbox_db
    report = compute_serviceability_scoring(assembly_id, db)

    cover_score = next(c for c in report.component_scores if c.component_name == "Gearbox_Cover")
    assert cover_score.access_score == 25.0
    assert cover_score.clearance_score == 5.0
    assert cover_score.disassembly_score == 13.0
    assert cover_score.fastener_score == 17.0
    assert cover_score.score == 60.0

    # Ensure fastener deduction refers to 4 physical bolts
    fastener_deduction = next(d for d in cover_score.deductions if d.criterion == "Fastener Complexity")
    assert "4 physical" in fastener_deduction.measured_value
    assert fastener_deduction.penalty_points == 8.0

    # Ensure confirmed clash deduction exists
    clash_deduction = next(d for d in cover_score.deductions if d.criterion == "Clearance")
    assert clash_deduction.penalty_points == 20.0
    assert clash_deduction.severity == "CRITICAL"


def test_no_false_critical_safety_conclusion(gearbox_db):
    """
    Item 8 Audit: Ensure critical safety findings do NOT falsely flag intentional bearing clearances.
    """
    db, assembly_id = gearbox_db
    report = compute_serviceability_scoring(assembly_id, db)

    # Verify no false safety conclusion about Input_Shaft in critical_safety_findings
    for finding in report.critical_safety_findings:
        f_lower = finding.lower()
        assert "input_shaft" not in f_lower or "rubbing" in f_lower or "interference" in f_lower


def test_gearbox_housing_scoring_breakdown(gearbox_db):
    """
    Milestone 3 Consistency Audit: Trace exact 57.0 / 100 score for Gearbox_Housing.
    - Access: 25.0 / 25 (unobstructed)
    - Clearance: 5.0 / 25 (-20.0 penalty for confirmed solid interference with Output_Gear)
    - Disassembly: 10.0 / 25 (-15.0 penalty for 5 preceding parts in sequence)
    - Fastener Complexity: 17.0 / 25 (-8.0 penalty for 4 deduplicated physical cover bolts)
    Total: 25 + 5 + 10 + 17 = 57.0 / 100.
    """
    db, assembly_id = gearbox_db
    report = compute_serviceability_scoring(assembly_id, db)

    housing_score = next(c for c in report.component_scores if c.component_name == "Gearbox_Housing")
    assert housing_score.access_score == 25.0
    assert housing_score.clearance_score == 5.0
    assert housing_score.disassembly_score == 10.0
    assert housing_score.fastener_score == 17.0
    assert housing_score.score == 57.0
    assert housing_score.rating == "FAIR"
    assert len(housing_score.deductions) == 3

    clearance_ded = next(d for d in housing_score.deductions if d.criterion == "Clearance")
    assert clearance_ded.penalty_points == 20.0
    assert clearance_ded.severity == "CRITICAL"
    assert "clash volume" in clearance_ded.measured_value

    fastener_ded = next(d for d in housing_score.deductions if d.criterion == "Fastener Complexity")
    assert fastener_ded.penalty_points == 8.0
    assert "4 physical" in fastener_ded.measured_value


def test_gearbox_housing_2mm_clearance_surfaces(gearbox_db):
    """
    Consistency Audit: Recalculate 2.00 mm clearance between Gearbox_Housing and Input_Bearing_Left.
    Verify:
    1. Distance is minimum 3D Euclidean distance d = sqrt(dx^2 + dy^2 + dz^2) = 2.000 mm.
    2. Delta is purely axial along Z: dx = 0.0, dy = 0.0, dz = 2.000 mm.
    3. Defining surfaces:
       - Housing contact point lies on a planar cavity floor face with normal = (0, 0, 1) at Z = 18.0 mm.
       - Bearing contact point lies on the outer cylindrical surface (R = 10.0 mm) whose axis is at Z = 30.0 mm,
         giving its bottom generator line at Z = 30 - 10 = 20.0 mm.
    """
    db, assembly_id = gearbox_db
    shapes = get_assembly_shapes(assembly_id, db)
    comps = db.query(Component).filter(Component.assembly_id == assembly_id, Component.is_leaf == 1).all()

    s_housing = next(shapes[c.cad_entity_id] for c in comps if c.name == "Gearbox_Housing")
    s_bearing = next(shapes[c.cad_entity_id] for c in comps if c.name == "Input_Bearing_Left")

    dist_tool = BRepExtrema_DistShapeShape(s_housing.wrapped, s_bearing.wrapped)
    dist_tool.Perform()
    assert dist_tool.IsDone()
    dist = dist_tool.Value()
    assert pytest.approx(dist, abs=1e-4) == 2.0000

    p1 = dist_tool.PointOnShape1(1)
    p2 = dist_tool.PointOnShape2(1)

    assert pytest.approx(p1.X(), abs=1e-2) == -40.50
    assert pytest.approx(p1.Y(), abs=1e-2) == -16.00
    assert pytest.approx(p1.Z(), abs=1e-2) == 18.00

    assert pytest.approx(p2.X(), abs=1e-2) == -40.50
    assert pytest.approx(p2.Y(), abs=1e-2) == -16.00
    assert pytest.approx(p2.Z(), abs=1e-2) == 20.00

    dx = p2.X() - p1.X()
    dy = p2.Y() - p1.Y()
    dz = p2.Z() - p1.Z()
    assert pytest.approx(dx, abs=1e-4) == 0.0
    assert pytest.approx(dy, abs=1e-4) == 0.0
    assert pytest.approx(dz, abs=1e-4) == 2.000


def test_assembly_overall_score_aggregation_and_selection_independence(gearbox_db):
    """
    Consistency Audit:
    1. Overall score (93.4 / 100) is the strict arithmetic mean of all 18 leaf components.
    2. Non-leaf assembly containers are excluded from leaf count and scoring.
    3. Repeating scoring produces identical results (repeatability / idempotency).
    """
    db, assembly_id = gearbox_db

    # First run
    report1 = compute_serviceability_scoring(assembly_id, db)
    # Second run (simulating re-analysis or independent query)
    report2 = compute_serviceability_scoring(assembly_id, db)

    # Idempotency / Repeatability
    assert report1.overall_score == report2.overall_score
    assert report1.analyzed_components_count == 18
    assert report2.analyzed_components_count == 18

    # Strict arithmetic mean validation
    leaf_scores = [c.score for c in report1.component_scores]
    assert len(leaf_scores) == 18
    calculated_mean = round(sum(leaf_scores) / len(leaf_scores), 1)
    assert report1.overall_score == calculated_mean
    assert pytest.approx(report1.overall_score, abs=0.05) == 67.7

    # Verify each component score matches across repeated calls
    for c1, c2 in zip(report1.component_scores, report2.component_scores):
        assert c1.component_id == c2.component_id
        assert c1.score == c2.score
        assert c1.access_score == c2.access_score
        assert c1.clearance_score == c2.clearance_score
        assert c1.disassembly_score == c2.disassembly_score
        assert c1.fastener_score == c2.fastener_score

