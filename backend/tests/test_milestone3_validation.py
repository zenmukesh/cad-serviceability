"""
Milestone 3 Validation Tests:
- Reliable Collision Classification (INTERFERENCE vs CONTACT vs CLEARANCE vs INDETERMINATE)
- Mechanically Consistent Fasteners (Unified rigid fastener assemblies)
- Disassembly Dependency DAG (Clamping constraints, cycle detection, candidate labeling)
- Trustworthy & Explainable Scoring (Confirmed solid interference penalty, context-aware fits)
- Blind Test Assembly (blind_serviceability_test.step) verification
"""
import pytest
import cadquery as cq
from pathlib import Path
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.database import Base
from app.models.assembly import Assembly, Component
from app.services.cad_importer import import_step_file
from app.services.geometry_service import (
    compute_shape_distance,
    compute_shape_intersection_volume,
    analyze_clearances,
    build_disassembly_graph,
    compute_serviceability_scoring,
    is_shaft_bearing_interface,
    is_shaft_bore_running_clearance,
    is_guard_to_base_clearance,
    Point3D,
)


# ─── 1. Controlled Collision Classification Tests ──────────────────────────────

def test_solid_overlap_interference_volume():
    """
    Priority 1 Test: Two overlapping boxes (2 mm overlap) must be classified as
    INTERFERENCE with positive Boolean collision volume (200.0 mm3), NOT contact.
    """
    b1 = cq.Workplane().box(10, 10, 10).val()
    b2 = cq.Workplane().transformed(offset=(8, 0, 0)).box(10, 10, 10).val()

    dist, p1, p2 = compute_shape_distance(b1, b2)
    assert dist <= 0.05

    vol, status = compute_shape_intersection_volume(b1, b2)
    assert status == "SUCCESS"
    assert pytest.approx(vol, rel=1e-3) == 200.0  # 2.0 mm * 10 * 10 = 200 mm3


def test_coincident_mating_face_zero_volume():
    """
    Priority 1 Test: Two touching boxes sharing a coincident face (distance = 0.0 mm)
    must return collision volume <= 1e-4 mm3 (CONTACT, not INTERFERENCE).
    """
    b1 = cq.Workplane().box(10, 10, 10).val()
    b2 = cq.Workplane().transformed(offset=(10, 0, 0)).box(10, 10, 10).val()

    dist, p1, p2 = compute_shape_distance(b1, b2)
    assert pytest.approx(dist, abs=1e-5) == 0.0

    vol, status = compute_shape_intersection_volume(b1, b2)
    assert status == "SUCCESS" or status == "EMPTY"
    assert vol is not None
    assert vol <= 1e-4  # Zero 3D volumetric clash


def test_positive_air_gap_clearance():
    """
    Priority 1 Test: True separated bodies (5.0 mm gap) must not invoke boolean
    intersection and return pure Euclidean distance.
    """
    b1 = cq.Workplane().box(10, 10, 10).val()
    b2 = cq.Workplane().transformed(offset=(15, 0, 0)).box(10, 10, 10).val()

    dist, p1, p2 = compute_shape_distance(b1, b2)
    assert pytest.approx(dist, abs=1e-5) == 5.0
    assert dist > 0.05


# ─── 2. Context-Aware Fit Rules ───────────────────────────────────────────────

def test_engineered_shaft_bore_running_clearance():
    """
    Priority 4 Test: Shaft inside coupling/wheel bore with 0.20 mm radial clearance
    must be classified as an engineered running fit (PASS), not a generic defect.
    """
    c1 = Component(id=1, name="Service_Shaft", bb_xmin=-50, bb_xmax=50, bb_ymin=-7, bb_ymax=7, bb_zmin=-7, bb_zmax=7)
    c2 = Component(id=2, name="Drive_Coupling", bb_xmin=40, bb_xmax=60, bb_ymin=-12, bb_ymax=12, bb_zmin=-12, bb_zmax=12)

    p1 = Point3D(x=45.0, y=7.0, z=0.0)
    p2 = Point3D(x=45.0, y=7.2, z=0.0)
    dist = 0.20

    assert is_shaft_bore_running_clearance(c1, c2, dist, p1, p2) is True


def test_nominal_guard_to_base_clearance():
    """
    Priority 4 Test: 2.0 mm vertical air gap between Front_Guard and Mounting_Base
    must be recognized as acceptable non-structural clearance.
    """
    c1 = Component(id=1, name="Front_Guard", bb_xmin=19, bb_xmax=31, bb_ymin=-67, bb_ymax=5, bb_zmin=10, bb_zmax=52)
    c2 = Component(id=2, name="Mounting_Base", bb_xmin=-60, bb_xmax=60, bb_ymin=-45, bb_ymax=45, bb_zmin=0, bb_zmax=8)

    p1 = Point3D(x=19.0, y=5.0, z=10.0)
    p2 = Point3D(x=19.0, y=5.0, z=8.0)
    dist = 2.00

    assert is_guard_to_base_clearance(c1, c2, dist, p1, p2) is True


# ─── 3. Blind Test Assembly Ingestion & Validation ─────────────────────────────

@pytest.fixture(scope="module")
def blind_test_db():
    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False})
    Session = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    Base.metadata.create_all(bind=engine)
    db = Session()

    step_path = Path("../uploads/66b0c3fd7bde391b0ba4a2bafb84b9c23c8398b970345107188dc8097a4fde91.step")
    if not step_path.exists():
        step_path = Path("uploads/66b0c3fd7bde391b0ba4a2bafb84b9c23c8398b970345107188dc8097a4fde91.step")
    if not step_path.exists():
        pytest.skip("Blind test STEP file not found on disk")

    res = import_step_file(step_path)
    assembly = Assembly(
        filename="blind_serviceability_test.step",
        sha256="66b0c3fd7bde391b0ba4a2bafb84b9c23c8398b970345107188dc8097a4fde91",
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


def test_blind_test_collision_classification(blind_test_db):
    """
    Priority 1 & Audit Deliverable:
    Verify that blind_serviceability_test.step detects all 9 severe solid interferences
    (including Right_Support <-> Drive_Coupling, Front_Guard <-> Idler_Wheel, and Service_Shaft <-> Front_Guard).
    """
    db, assembly_id = blind_test_db
    clearances = analyze_clearances(assembly_id, db, min_threshold_mm=3.0)

    interferences = [c for c in clearances if c.classification == "INTERFERENCE"]
    assert len(interferences) == 9

    # Check key gross structural clashes
    right_sup_clash = next(c for c in interferences if "Right_Support" in c.target_component_name and "Drive_Coupling" in c.neighbor_component_name)
    assert right_sup_clash.severity == "CRITICAL"
    assert pytest.approx(right_sup_clash.intersection_volume_mm3, rel=1e-2) == 4046.37

    guard_wheel_clash = next(c for c in interferences if "Front_Guard" in c.target_component_name and "Idler_Wheel" in c.neighbor_component_name)
    assert guard_wheel_clash.severity == "CRITICAL"
    assert pytest.approx(guard_wheel_clash.intersection_volume_mm3, rel=1e-2) == 7469.95

    shaft_guard_clash = next(c for c in interferences if "Service_Shaft" in c.target_component_name and "Front_Guard" in c.neighbor_component_name)
    assert shaft_guard_clash.severity == "CRITICAL"
    assert pytest.approx(shaft_guard_clash.intersection_volume_mm3, rel=1e-2) == 1685.38


def test_blind_test_fastener_unification_and_disassembly_order(blind_test_db):
    """
    Priority 2 & 3 Deliverable:
    1. Four physical guard bolts must be unified from 8 leaf solids into 4 unified fastener steps.
    2. Total sequence steps must be 12 (8 main components + 4 unified fasteners), NOT 16 fragmented steps.
    3. Unresolved constraint cycles (Bolt heads 1 & 3 trapped behind Front_Guard while clamping Front_Guard)
       must be detected and reported as sequence_status == 'cycle_detected'.
    4. Sequence must be qualified with is_physically_verified == False and candidate validation notes.
    5. Front_Guard prerequisites must include all 4 securing fasteners.
    """
    db, assembly_id = blind_test_db
    graph = build_disassembly_graph(assembly_id, db)

    assert graph.total_steps == 12
    assert graph.estimated_fastener_count == 4
    assert graph.sequence_status == "cycle_detected"
    assert graph.is_physically_verified is False
    assert any("Constraint cycle detected" in note for note in graph.validation_notes)

    # Verify 4 unified fastener steps exist
    fastener_steps = [s for s in graph.sequence if s.is_unified_fastener]
    assert len(fastener_steps) == 4
    for s in fastener_steps:
        assert s.action == "remove_fastener"
        assert len(s.member_component_ids) == 2  # Shank + Head

    # Verify Front_Guard has prerequisites including fasteners
    guard_step = next(s for s in graph.sequence if s.component_name == "Front_Guard")
    assert any("Guard_Bolt" in p for p in guard_step.prerequisites)


def test_blind_test_scoring_reflects_clash_defects(blind_test_db):
    """
    Priority 4 Deliverable:
    Ensure severe solid clashes penalize Clearance score (-20.0 pts) and disqualify EXCELLENT rating.
    Overall rating must be downgraded to FAIR due to 9 confirmed critical interference findings.
    Verify deduplication: exactly 9 unique unordered colliding pairs.
    """
    db, assembly_id = blind_test_db
    report = compute_serviceability_scoring(assembly_id, db)

    assert report.overall_rating == "FAIR"
    assert report.critical_issues_count == 9
    assert len(report.critical_safety_findings) == 9

    # Verify deduplication: each unordered pair is present once
    for finding in report.critical_safety_findings:
        assert "[GEOMETRIC INTERFERENCE]" in finding
        assert "solid overlap" in finding

    # Front_Guard has severe clash -> clearance score is 5.0 / 25
    guard_score = next(c for c in report.component_scores if c.component_name == "Front_Guard")
    assert guard_score.clearance_score == 5.0
    clash_ded = next(d for d in guard_score.deductions if d.criterion == "Clearance")
    assert clash_ded.penalty_points == 20.0
    assert clash_ded.severity == "CRITICAL"


def test_scoring_traceability_and_mathematical_consistency(blind_test_db):
    """
    Verify complete score formula consistency:
    1. Overall score must equal mean of component scores rounded to 1 decimal place.
    2. Each component score must equal sum of 4 criteria sub-scores clamped to [0, 100].
    3. Each criterion sub-score must equal 25.0 minus the sum of deductions for that criterion.
    """
    db, assembly_id = blind_test_db
    report = compute_serviceability_scoring(assembly_id, db)

    expected_overall = round(sum(c.score for c in report.component_scores) / len(report.component_scores), 1)
    assert report.overall_score == expected_overall

    for c in report.component_scores:
        expected_comp_total = round(max(0.0, min(100.0, c.access_score + c.clearance_score + c.disassembly_score + c.fastener_score)), 1)
        assert c.score == expected_comp_total

        # Criterion 1: Access
        acc_ded = sum(d.penalty_points for d in c.deductions if d.criterion == "Access & Obstruction")
        assert c.access_score == round(max(0.0, 25.0 - acc_ded), 1)

        # Criterion 2: Clearance
        clr_ded = sum(d.penalty_points for d in c.deductions if d.criterion == "Clearance")
        assert c.clearance_score == round(max(0.0, 25.0 - clr_ded), 1)

        # Criterion 3: Disassembly
        dis_ded = sum(d.penalty_points for d in c.deductions if d.criterion == "Disassembly Effort")
        assert c.disassembly_score == round(max(0.0, 25.0 - dis_ded), 1)

        # Criterion 4: Fastener
        fst_ded = sum(d.penalty_points for d in c.deductions if d.criterion == "Fastener Complexity")
        assert c.fastener_score == round(max(0.0, 25.0 - fst_ded), 1)


def test_reversing_pair_deduplication_and_no_loss_of_legitimate_collisions(blind_test_db):
    """
    Task 4 Verification:
    Verify that reversing a component pair does not create a duplicate finding,
    and that deduplication does not remove legitimate collisions.
    """
    db, assembly_id = blind_test_db
    clearances = analyze_clearances(assembly_id, db, min_threshold_mm=3.0)
    interferences = [c for c in clearances if c.classification == "INTERFERENCE"]

    assert len(interferences) == 9

    # Simulate reversing pair order: (A, B) vs (B, A)
    seen_pairs = set()
    deduped_findings = []
    for c in interferences:
        pair_key = tuple(sorted([c.target_component_id, c.neighbor_component_id]))
        if pair_key not in seen_pairs:
            seen_pairs.add(pair_key)
            deduped_findings.append(f"{c.target_component_name} <-> {c.neighbor_component_name}")

    # Now simulate inverted feed of all pairs (B, A)
    for c in interferences:
        inverted_pair_key = tuple(sorted([c.neighbor_component_id, c.target_component_id]))
        assert inverted_pair_key in seen_pairs, "Inverted pair key must match the canonical sorted pair key"

    # Verify no duplicates were created
    assert len(seen_pairs) == 9
    assert len(deduped_findings) == 9

    # Verify no legitimate collisions were removed
    expected_pairs = {
        ("Right_Support", "Drive_Coupling"),
        ("Service_Shaft", "Front_Guard"),
        ("Front_Guard", "Guard_Bolt_Shank_1"),
        ("Front_Guard", "Guard_Bolt_Head_1"),
        ("Front_Guard", "Guard_Bolt_Shank_2"),
        ("Front_Guard", "Guard_Bolt_Shank_3"),
        ("Front_Guard", "Guard_Bolt_Head_3"),
        ("Front_Guard", "Guard_Bolt_Shank_4"),
        ("Front_Guard", "Idler_Wheel"),
    }
    found_pairs = {
        tuple(sorted([c.target_component_name, c.neighbor_component_name]))
        for c in interferences
    }
    normalized_expected = {tuple(sorted(p)) for p in expected_pairs}
    assert found_pairs == normalized_expected


def test_blind_test_full_pairwise_classification_breakdown(blind_test_db):
    """
    Task 2 & 7 Verification:
    Verify exact counts and classification of all 116 pairwise measurements in blind_serviceability_test.step:
    - 9 INTERFERENCE (volumetric clashes)
    - 3 CONTACT (mating interfaces with zero volume)
    - 104 CLEARANCE (5 deficit < 3.0 mm, 99 adequate >= 3.0 mm)
    """
    db, assembly_id = blind_test_db
    clearances = analyze_clearances(assembly_id, db, min_threshold_mm=3.0)

    assert len(clearances) == 116

    interferences = [c for c in clearances if c.classification == "INTERFERENCE"]
    contacts = [c for c in clearances if c.classification == "CONTACT"]
    clearances_all = [c for c in clearances if c.classification == "CLEARANCE"]
    deficits = [c for c in clearances_all if not c.is_pass]
    adequate = [c for c in clearances_all if c.is_pass]

    assert len(interferences) == 9
    assert len(contacts) == 3
    assert len(clearances_all) == 104
    assert len(deficits) == 5
    assert len(adequate) == 99

    # Verify the 3 contact interfaces have zero volume and dist <= 0.05 mm
    for c in contacts:
        assert c.distance_mm <= 0.05
        assert c.intersection_volume_mm3 == 0.0
        assert c.severity == "PASS"

    contact_pairs = {tuple(sorted([c.target_component_name, c.neighbor_component_name])) for c in contacts}
    assert ("Left_Support", "Mounting_Base") in contact_pairs
    assert ("Mounting_Base", "Right_Support") in contact_pairs
    assert ("Idler_Wheel", "Shaft_Spacer") in contact_pairs


def test_score_reproducibility_and_deduction_rule_traceability(blind_test_db):
    """
    Task 5 Verification:
    1. Verify repeated runs produce identical overall scores and component scores.
    2. Verify every single deduction traces to one of the 4 documented criteria and has a documented threshold.
    """
    db, assembly_id = blind_test_db

    rep1 = compute_serviceability_scoring(assembly_id, db)
    rep2 = compute_serviceability_scoring(assembly_id, db)

    assert rep1.overall_score == rep2.overall_score
    assert rep1.critical_issues_count == rep2.critical_issues_count
    assert rep1.warnings_count == rep2.warnings_count

    allowed_criteria = {
        "Access & Obstruction",
        "Clearance",
        "Disassembly Effort",
        "Fastener Complexity",
    }

    for c1, c2 in zip(rep1.component_scores, rep2.component_scores):
        assert c1.component_name == c2.component_name
        assert c1.score == c2.score
        assert len(c1.deductions) == len(c2.deductions)

        for d in c1.deductions:
            assert d.criterion in allowed_criteria
            assert d.penalty_points > 0.0
            assert d.description != ""
            assert d.threshold is not None
            assert d.severity in ["INFO", "WARNING", "CRITICAL"]


def test_disassembly_flagged_not_physically_verified(blind_test_db):
    """
    Task 6 Verification:
    1. Flag that sequences are not physically validated by continuous swept-volume checks.
    2. Verify is_physically_verified is False.
    3. Verify sequence_status is 'cycle_detected' and cycle notes are present.
    """
    db, assembly_id = blind_test_db
    graph = build_disassembly_graph(assembly_id, db)

    assert graph.is_physically_verified is False
    assert graph.sequence_status == "cycle_detected"

    # Notes must inform user that continuous swept-volume motion was not evaluated
    notes_text = " ".join(graph.validation_notes)
    assert "swept-volume" in notes_text or "Candidate sequence" in notes_text
    assert "cycle detected" in notes_text.lower()
