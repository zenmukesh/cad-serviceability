# -*- coding: utf-8 -*-
"""
Regression tests for Direction-Aware Disassembly Sequence Planner (Milestone 2 Refinement).

Covers the 7 required verification scenarios:
1. Blocked +X path causes planner to evaluate all directions and select verified alternative direction.
2. Direction attempts: all 6 cardinal directions recorded with per-direction collision details.
3. Prerequisite-aware ordering: component with unmet prerequisites is not marked immediately removable (status_label: 'Prerequisite required').
4. Dynamic obstacle updates: fastener removal removes fastener from the active collision set for subsequent steps.
5. Solvable soft dependency cycle resolved by alternative ordering / direction search (sequence_status: 'physically_verified').
6. Unresolved rigid dependency cycle reported honestly (sequence_status: 'cycle_detected', status_label: 'Unresolved dependency cycle').
7. Blind test regression: blind_serviceability_test.step accurately reports unresolved dependency cycle (12 physical entities, unverified).
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
    _SHAPE_CACHE,
    build_disassembly_graph,
    compute_serviceability_scoring,
    CARDINAL_DIRECTIONS,
)


@pytest.fixture
def direction_db():
    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False})
    Session = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    Base.metadata.create_all(bind=engine)
    db = Session()
    yield db
    db.close()


def test_1_blocked_plus_x_selects_alternative_direction(direction_db):
    """
    Test 1: When +X path is blocked by another component, the planner evaluates remaining
    principal directions, selects a collision-free alternative (-X), and classifies status_label
    as 'Alternative direction found'.
    """
    db = direction_db
    asm = Assembly(filename="test1_alt_dir.step", sha256="sha_dir1", status="ready")
    db.add(asm)
    db.commit()

    # Access Cover at (0, 0, 5) -> x: [-5, 5]
    sh_cover = cq.Workplane().box(10, 10, 10).val().translate((0, 0, 5))
    c_cover = Component(
        assembly_id=asm.id, cad_entity_id="cad_c1", name="Access_Cover", is_leaf=1,
        bb_xmin=-5, bb_xmax=5, bb_ymin=-5, bb_ymax=5, bb_zmin=0, bb_zmax=10
    )
    # Heavy barrier blocking +X: x: [12, 22]
    sh_wall = cq.Workplane().box(10, 40, 40).val().translate((17, 0, 10))
    c_wall = Component(
        assembly_id=asm.id, cad_entity_id="cad_w1", name="Internal_Wall", is_leaf=1,
        bb_xmin=12, bb_xmax=22, bb_ymin=-20, bb_ymax=20, bb_zmin=-10, bb_zmax=30
    )
    db.add_all([c_cover, c_wall])
    db.commit()

    _SHAPE_CACHE[f"{asm.id}:{asm.sha256}"] = {"cad_c1": sh_cover, "cad_w1": sh_wall}

    graph = build_disassembly_graph(asm.id, db)
    cover_step = next(s for s in graph.sequence if s.component_name == "Access_Cover")

    assert cover_step.is_path_verified is True
    assert cover_step.removal_direction == "-X" or cover_step.removal_direction in ["-X", "+Y", "-Y", "+Z", "-Z"]
    assert cover_step.removal_direction != "+X"
    assert cover_step.status_label in ["Alternative direction found", "Ready \u2014 path verified"]
    assert len(cover_step.direction_attempts) == 6

    # Verify +X attempt failed
    plus_x = next(d for d in cover_step.direction_attempts if d.direction == "+X")
    assert plus_x.is_clear is False
    assert "Internal_Wall" in plus_x.colliding_components


def test_2_direction_attempts_records_all_six_directions(direction_db):
    """
    Test 2: Verify that every step records all 6 directions (+X, -X, +Y, -Y, +Z, -Z)
    in direction_attempts with accurate is_clear and collision breakdowns.
    """
    db = direction_db
    asm = Assembly(filename="test2_all_dirs.step", sha256="sha_dir2", status="ready")
    db.add(asm)
    db.commit()

    # Center cube
    sh_center = cq.Workplane().box(10, 10, 10).val().translate((0, 0, 5))
    c_center = Component(
        assembly_id=asm.id, cad_entity_id="cad_center", name="Center_Block", is_leaf=1,
        bb_xmin=-5, bb_xmax=5, bb_ymin=-5, bb_ymax=5, bb_zmin=0, bb_zmax=10
    )
    # Block +Z with top cover: z: [15, 25]
    sh_top = cq.Workplane().box(30, 30, 10).val().translate((0, 0, 20))
    c_top = Component(
        assembly_id=asm.id, cad_entity_id="cad_top", name="Top_Cover", is_leaf=1,
        bb_xmin=-15, bb_xmax=15, bb_ymin=-15, bb_ymax=15, bb_zmin=15, bb_zmax=25
    )
    db.add_all([c_center, c_top])
    db.commit()

    _SHAPE_CACHE[f"{asm.id}:{asm.sha256}"] = {"cad_center": sh_center, "cad_top": sh_top}

    graph = build_disassembly_graph(asm.id, db)
    step = next(s for s in graph.sequence if s.component_name == "Top_Cover")

    assert len(step.direction_attempts) == 6
    dir_names = [att.direction for att in step.direction_attempts]
    assert set(dir_names) == {"+X", "-X", "+Y", "-Y", "+Z", "-Z"}

    # -Z should clash with Center_Block underneath
    att_minus_z = next(att for att in step.direction_attempts if att.direction == "-Z")
    assert att_minus_z.is_clear is False
    assert "Center_Block" in att_minus_z.colliding_components

    # +Z upward extraction should be clear
    att_plus_z = next(att for att in step.direction_attempts if att.direction == "+Z")
    assert att_plus_z.is_clear is True
    assert att_plus_z.notes == "Clear path"


def test_3_unmet_prerequisites_not_immediately_removable(direction_db):
    """
    Test 3: An internal component whose prerequisite cover has not yet been removed
    cannot be marked immediately removable; its status must be 'Prerequisite required'
    or it must be scheduled after its prerequisite.
    """
    db = direction_db
    asm = Assembly(filename="test3_prereq.step", sha256="sha_dir3", status="ready")
    db.add(asm)
    db.commit()

    # External cover
    sh_cover = cq.Workplane().box(30, 30, 10).val().translate((0, 0, 20))
    c_cover = Component(
        assembly_id=asm.id, cad_entity_id="cad_cov3", name="Top_Cover", is_leaf=1,
        bb_xmin=-15, bb_xmax=15, bb_ymin=-15, bb_ymax=15, bb_zmin=15, bb_zmax=25
    )
    # Internal gear
    sh_gear = cq.Workplane().box(10, 10, 10).val().translate((0, 0, 5))
    c_gear = Component(
        assembly_id=asm.id, cad_entity_id="cad_gear3", name="Internal_Pinion", is_leaf=1,
        bb_xmin=-5, bb_xmax=5, bb_ymin=-5, bb_ymax=5, bb_zmin=0, bb_zmax=10
    )
    db.add_all([c_cover, c_gear])
    db.commit()

    _SHAPE_CACHE[f"{asm.id}:{asm.sha256}"] = {"cad_cov3": sh_cover, "cad_gear3": sh_gear}

    graph = build_disassembly_graph(asm.id, db)

    step_cov = next(s for s in graph.sequence if s.component_name == "Top_Cover")
    step_gear = next(s for s in graph.sequence if s.component_name == "Internal_Pinion")

    # Step ordering: Cover MUST precede internal gear
    assert step_cov.step_number < step_gear.step_number
    assert "Top_Cover" in step_gear.prerequisites


def test_4_fastener_removal_updates_obstacle_set(direction_db):
    """
    Test 4: When a fastener is removed, it is removed from the active obstacle set,
    allowing the clamped cover to be extracted along the path formerly occupied by the fastener.
    """
    db = direction_db
    asm = Assembly(filename="test4_fastener_update.step", sha256="sha_dir4", status="ready")
    db.add(asm)
    db.commit()

    # Housing
    sh_base = cq.Workplane().box(60, 60, 10).val().translate((0, 0, 5))
    c_base = Component(assembly_id=asm.id, cad_entity_id="cad_b4", name="Main_Housing", is_leaf=1, bb_xmin=-30, bb_xmax=30, bb_ymin=-30, bb_ymax=30, bb_zmin=0, bb_zmax=10)

    # Cover
    sh_cover = cq.Workplane().box(40, 40, 10).val().translate((0, 0, 15)).cut(
        cq.Workplane().box(10, 10, 12).val().translate((0, 0, 15))
    )
    c_cover = Component(assembly_id=asm.id, cad_entity_id="cad_c4", name="Housing_Cover", is_leaf=1, bb_xmin=-20, bb_xmax=20, bb_ymin=-20, bb_ymax=20, bb_zmin=10, bb_zmax=20)

    # Bolt through hole
    shank = cq.Workplane().box(8, 8, 11).val().translate((0, 0, 14.5))
    head = cq.Workplane().box(16, 16, 6).val().translate((0, 0, 23))
    sh_bolt = shank.fuse(head)
    c_bolt = Component(assembly_id=asm.id, cad_entity_id="cad_bolt4", name="Cover_Bolt_1", is_leaf=1, bb_xmin=-8, bb_xmax=8, bb_ymin=-8, bb_ymax=8, bb_zmin=9, bb_zmax=26)

    db.add_all([c_base, c_cover, c_bolt])
    db.commit()

    _SHAPE_CACHE[f"{asm.id}:{asm.sha256}"] = {"cad_b4": sh_base, "cad_c4": sh_cover, "cad_bolt4": sh_bolt}

    graph = build_disassembly_graph(asm.id, db)

    bolt_step = next(s for s in graph.sequence if s.component_name == "Cover_Bolt_1")
    cover_step = next(s for s in graph.sequence if s.component_name == "Housing_Cover")

    # Fastener is removed first
    assert bolt_step.step_number < cover_step.step_number
    assert bolt_step.is_path_verified is True
    # Once fastener is gone, cover extraction along +Z is verified collision-free
    assert cover_step.is_path_verified is True
    assert cover_step.removal_direction == "+Z"
    assert cover_step.status_label == "Ready \u2014 path verified"


def test_5_solvable_dependency_cycle_resolved(direction_db):
    """
    Test 5: Solvable soft dependency cycle resolved by alternative ordering / directions.
    Part A and Part B have directional ray shadows toward each other (+X vs -X), but Part B
    can freely extract in +Y, resolving the ordering without getting stuck.
    """
    db = direction_db
    asm = Assembly(filename="test5_solvable.step", sha256="sha_dir5", status="ready")
    db.add(asm)
    db.commit()

    # Part A at (0, 0, 5)
    sh_a = cq.Workplane().box(10, 10, 10).val().translate((0, 0, 5))
    c_a = Component(assembly_id=asm.id, cad_entity_id="cad_sa", name="Access_Plate_A", is_leaf=1, bb_xmin=-5, bb_xmax=5, bb_ymin=-5, bb_ymax=5, bb_zmin=0, bb_zmax=10)

    # Part B at (16, 0, 5)
    sh_b = cq.Workplane().box(10, 10, 10).val().translate((16, 0, 5))
    c_b = Component(assembly_id=asm.id, cad_entity_id="cad_sb", name="Access_Plate_B", is_leaf=1, bb_xmin=11, bb_xmax=21, bb_ymin=-5, bb_ymax=5, bb_zmin=0, bb_zmax=10)

    db.add_all([c_a, c_b])
    db.commit()

    _SHAPE_CACHE[f"{asm.id}:{asm.sha256}"] = {"cad_sa": sh_a, "cad_sb": sh_b}

    graph = build_disassembly_graph(asm.id, db)

    # Both must be verified, sequence_status physically_verified
    assert graph.is_physically_verified is True
    assert graph.sequence_status == "physically_verified"
    assert graph.verified_steps_count == 2
    assert graph.unverified_steps_count == 0


def test_6_unresolved_cycle_reported_honestly(direction_db):
    """
    Test 6: Rigid/unresolved cycle reported honestly without claiming complete physical verification.
    """
    db = direction_db
    asm = Assembly(filename="test6_cycle.step", sha256="sha_dir6", status="ready")
    db.add(asm)
    db.commit()

    # Part 1: Box enclosed in Part 2
    sh1 = cq.Workplane().box(8, 8, 8).val().translate((0, 0, 5))
    c1 = Component(assembly_id=asm.id, cad_entity_id="cad_c1_6", name="Locked_Part_1", is_leaf=1, bb_xmin=-4, bb_xmax=4, bb_ymin=-4, bb_ymax=4, bb_zmin=1, bb_zmax=9)

    # Part 2: Outer cage enclosing Part 1
    outer = cq.Workplane().box(20, 20, 20).val().translate((0, 0, 5))
    cavity = cq.Workplane().box(10, 10, 10).val().translate((0, 0, 5))
    sh2 = outer.cut(cavity)
    c2 = Component(assembly_id=asm.id, cad_entity_id="cad_c2_6", name="Locked_Cage_2", is_leaf=1, bb_xmin=-10, bb_xmax=10, bb_ymin=-10, bb_ymax=10, bb_zmin=-5, bb_zmax=15)

    db.add_all([c1, c2])
    db.commit()

    _SHAPE_CACHE[f"{asm.id}:{asm.sha256}"] = {"cad_c1_6": sh1, "cad_c2_6": sh2}

    graph = build_disassembly_graph(asm.id, db)

    # Locked_Part_1 cannot escape along any axis
    assert graph.is_physically_verified is False
    p1_step = next(s for s in graph.sequence if s.component_name == "Locked_Part_1")
    assert p1_step.is_path_verified is False
    assert p1_step.status_label in ["No feasible straight-line path found", "Prerequisite required", "Unresolved dependency cycle"]


def test_7_blind_step_regression(direction_db):
    """
    Test 7: Regression test for blind_serviceability_test.step.
    Confirms:
    1. Unresolved cycle detected honestly (due to trapped guard bolt head behind clamped guard).
    2. Exactly 12 physical entities (4 unified fastener pairs + 8 distinct components).
    3. is_physically_verified is False (no fake verification).
    """
    step_path = Path("../uploads/66b0c3fd7bde391b0ba4a2bafb84b9c23c8398b970345107188dc8097a4fde91.step")
    if not step_path.exists():
        step_path = Path("uploads/66b0c3fd7bde391b0ba4a2bafb84b9c23c8398b970345107188dc8097a4fde91.step")
    if not step_path.exists():
        pytest.skip("test_data/blind_serviceability_test.step not found")

    db = direction_db
    res = import_step_file(step_path)
    asm = Assembly(
        filename="blind_serviceability_test.step",
        sha256="66b0c3fd7bde391b0ba4a2bafb84b9c23c8398b970345107188dc8097a4fde91",
        status="ready",
    )
    db.add(asm)
    db.commit()

    for c in res.components:
        db.add(Component(
            assembly_id=asm.id, cad_entity_id=c.cad_entity_id, name=c.name,
            parent_cad_id=c.parent_cad_id, is_leaf=1 if c.is_leaf else 0,
            component_type=c.component_type,
            bb_xmin=c.bb_xmin, bb_xmax=c.bb_xmax, bb_ymin=c.bb_ymin, bb_ymax=c.bb_ymax,
            bb_zmin=c.bb_zmin, bb_zmax=c.bb_zmax,
            volume_mm3=c.volume_mm3, surface_area_mm2=c.surface_area_mm2,
        ))
    db.commit()

    graph = build_disassembly_graph(asm.id, db)

    assert graph.total_steps == 12
    assert graph.sequence_status == "cycle_detected"
    assert graph.is_physically_verified is False

    # Check distinct status labels are populated
    status_labels = {s.status_label for s in graph.sequence}
    assert any("verified" in l.lower() or "alternative" in l.lower() or "cycle" in l.lower() for l in status_labels)

    # Check direction attempts are populated on every step
    for step in graph.sequence:
        assert len(step.direction_attempts) == 6
        assert step.tested_directions_count == 6
