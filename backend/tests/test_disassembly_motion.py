"""
Continuous Swept-Volume Disassembly Motion Validation Tests.

Validates proposed component removal trajectories with OpenCASCADE CAD Boolean simulation:
1. Unobstructed straight removal: Unconstrained component lifts into free space -> verified.
2. Blocked removal: Component translated along linear path collides with stationary solid -> collision detected.
3. Fastener-dependent removal: Fastener removed first unclamps cover, allowing unobstructed cover removal.
4. Cyclic / unresolved dependency: Fastener head trapped behind panel produces cycle and unverified status.
"""
import pytest
import cadquery as cq
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.database import Base
from app.models.assembly import Assembly, Component
from app.schemas.serviceability import DisassemblyGraph, DisassemblyStep
from app.services.geometry_service import (
    _SHAPE_CACHE,
    validate_disassembly_motion_paths,
    build_disassembly_graph,
)


@pytest.fixture
def memory_db():
    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False})
    Session = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    Base.metadata.create_all(bind=engine)
    db = Session()
    yield db
    db.close()


def test_unobstructed_straight_removal(memory_db):
    """
    Test 1: Unobstructed straight removal.
    A top pin sits on a base plate. Lifting the pin along +Z encounters no stationary
    obstacles. Motion validation must mark it verified with clear exit travel.
    """
    db = memory_db
    asm = Assembly(filename="unobstructed_test.step", sha256="unobstructed_sha", status="ready")
    db.add(asm)
    db.commit()

    base_shape = cq.Workplane().box(50, 50, 10).val().translate((0, 0, 5))
    c_base = Component(
        assembly_id=asm.id, cad_entity_id="c_base", name="Base_Plate", is_leaf=1,
        bb_xmin=-25, bb_xmax=25, bb_ymin=-25, bb_ymax=25, bb_zmin=0, bb_zmax=10,
    )
    db.add(c_base)

    pin_shape = cq.Workplane().box(10, 10, 20).val().translate((0, 0, 20))
    c_pin = Component(
        assembly_id=asm.id, cad_entity_id="c_pin", name="Top_Pin", is_leaf=1,
        bb_xmin=-5, bb_xmax=5, bb_ymin=-5, bb_ymax=5, bb_zmin=10, bb_zmax=30,
    )
    db.add(c_pin)
    db.commit()

    _SHAPE_CACHE[f"{asm.id}:{asm.sha256}"] = {"c_base": base_shape, "c_pin": pin_shape}

    graph = DisassemblyGraph(
        assembly_id=asm.id,
        sequence=[
            DisassemblyStep(
                step_number=1,
                component_id=c_pin.id,
                component_name="Top_Pin",
                cad_entity_id="c_pin",
                action="extract_component",
                removal_direction="+Z",
            )
        ],
        total_steps=1,
    )

    res = validate_disassembly_motion_paths(asm.id, db, graph)

    assert res.total_steps == 1
    step = res.sequence[0]
    assert step.is_path_verified is True
    assert step.path_validation_status == "verified"
    assert step.colliding_components_along_path == []
    assert step.max_verified_travel_mm is not None
    assert step.max_verified_travel_mm >= 25.0
    assert res.is_physically_verified is True
    assert res.sequence_status == "physically_verified"


def test_blocked_removal(memory_db):
    """
    Test 2: Blocked removal.
    A moving block translates along +X directly into a stationary obstacle wall.
    Continuous collision detection must catch the clash, identify the obstacle name,
    and mark the step as collision_detected with limited travel.
    """
    db = memory_db
    asm = Assembly(filename="blocked_test.step", sha256="blocked_sha", status="ready")
    db.add(asm)
    db.commit()

    block_shape = cq.Workplane().box(10, 10, 10).val().translate((0, 0, 5))
    c_block = Component(
        assembly_id=asm.id, cad_entity_id="c_block", name="Moving_Block", is_leaf=1,
        bb_xmin=-5, bb_xmax=5, bb_ymin=-5, bb_ymax=5, bb_zmin=0, bb_zmax=10,
    )
    db.add(c_block)

    wall_shape = cq.Workplane().box(10, 30, 30).val().translate((20, 0, 15))
    c_wall = Component(
        assembly_id=asm.id, cad_entity_id="c_wall", name="Obstacle_Wall", is_leaf=1,
        bb_xmin=15, bb_xmax=25, bb_ymin=-15, bb_ymax=15, bb_zmin=0, bb_zmax=30,
    )
    db.add(c_wall)
    db.commit()

    _SHAPE_CACHE[f"{asm.id}:{asm.sha256}"] = {"c_block": block_shape, "c_wall": wall_shape}

    graph = DisassemblyGraph(
        assembly_id=asm.id,
        sequence=[
            DisassemblyStep(
                step_number=1,
                component_id=c_block.id,
                component_name="Moving_Block",
                cad_entity_id="c_block",
                action="extract_component",
                removal_direction="+X",
            )
        ],
        total_steps=1,
    )

    res = validate_disassembly_motion_paths(asm.id, db, graph)

    assert res.total_steps == 1
    step = res.sequence[0]
    assert step.is_path_verified is False
    assert step.path_validation_status == "collision_detected"
    assert "Obstacle_Wall" in step.colliding_components_along_path
    assert step.max_verified_travel_mm is not None
    assert step.max_verified_travel_mm < 20.0
    assert res.is_physically_verified is False
    assert res.sequence_status == "candidate_with_path_collisions"


def test_fastener_dependent_removal(memory_db):
    """
    Test 3: Fastener-dependent removal.
    A retaining bolt clamps a cover plate to a base housing. The cover plate has a
    clearance hole allowing the bolt to slide out along +Z.
    - If the bolt is extracted first (Step 1), its path is verified clear.
    - When the cover is then removed (Step 2), the bolt is no longer present, so the cover
      lifts off unobstructed and is verified clear.
    - If the cover is attempted before the bolt, it violates prerequisite ordering.
    """
    db = memory_db
    asm = Assembly(filename="fastener_dep_test.step", sha256="fastener_dep_sha", status="ready")
    db.add(asm)
    db.commit()

    base_sh = cq.Workplane().box(60, 60, 10).val().translate((0, 0, 5))
    c_base = Component(
        assembly_id=asm.id, cad_entity_id="c_base", name="Base_Housing", is_leaf=1,
        bb_xmin=-30, bb_xmax=30, bb_ymin=-30, bb_ymax=30, bb_zmin=0, bb_zmax=10,
    )
    db.add(c_base)

    cover_solid = cq.Workplane().box(40, 40, 10).val().translate((0, 0, 15))
    hole_tool = cq.Workplane().box(9, 9, 12).val().translate((0, 0, 15))
    cover_sh = cover_solid.cut(hole_tool)
    c_cover = Component(
        assembly_id=asm.id, cad_entity_id="c_cover", name="Service_Cover", is_leaf=1,
        bb_xmin=-20, bb_xmax=20, bb_ymin=-20, bb_ymax=20, bb_zmin=10, bb_zmax=20,
    )
    db.add(c_cover)

    shank = cq.Workplane().box(8, 8, 11).val().translate((0, 0, 14.5))
    head = cq.Workplane().box(16, 16, 6).val().translate((0, 0, 23))
    bolt_sh = shank.fuse(head)
    c_bolt = Component(
        assembly_id=asm.id, cad_entity_id="c_bolt", name="Retaining_Bolt", is_leaf=1,
        bb_xmin=-8, bb_xmax=8, bb_ymin=-8, bb_ymax=8, bb_zmin=9, bb_zmax=26,
    )
    db.add(c_bolt)
    db.commit()

    _SHAPE_CACHE[f"{asm.id}:{asm.sha256}"] = {"c_base": base_sh, "c_cover": cover_sh, "c_bolt": bolt_sh}

    # Case A: Correct order (Bolt removed first, then Cover)
    graph_a = DisassemblyGraph(
        assembly_id=asm.id,
        sequence=[
            DisassemblyStep(
                step_number=1,
                component_id=c_bolt.id,
                component_name="Retaining_Bolt",
                cad_entity_id="c_bolt",
                action="remove_fastener",
                removal_direction="+Z",
            ),
            DisassemblyStep(
                step_number=2,
                component_id=c_cover.id,
                component_name="Service_Cover",
                cad_entity_id="c_cover",
                action="open_cover",
                removal_direction="+Z",
                prerequisites=["Retaining_Bolt"],
            ),
        ],
        total_steps=2,
    )

    res_a = validate_disassembly_motion_paths(asm.id, db, graph_a)
    assert res_a.is_physically_verified is True
    assert res_a.sequence_status == "physically_verified"
    assert res_a.sequence[0].is_path_verified is True
    assert res_a.sequence[0].path_validation_status == "verified"
    assert res_a.sequence[1].is_path_verified is True
    assert res_a.sequence[1].path_validation_status == "verified"

    # Case B: Out-of-order removal (Cover attempted before unbolting)
    graph_b = DisassemblyGraph(
        assembly_id=asm.id,
        sequence=[
            DisassemblyStep(
                step_number=1,
                component_id=c_cover.id,
                component_name="Service_Cover",
                cad_entity_id="c_cover",
                action="open_cover",
                removal_direction="+Z",
                prerequisites=["Retaining_Bolt"],
            ),
            DisassemblyStep(
                step_number=2,
                component_id=c_bolt.id,
                component_name="Retaining_Bolt",
                cad_entity_id="c_bolt",
                action="remove_fastener",
                removal_direction="+Z",
            ),
        ],
        total_steps=2,
    )

    res_b = validate_disassembly_motion_paths(asm.id, db, graph_b)
    assert res_b.is_physically_verified is False
    # Step 1 should fail due to prerequisite bolt still being installed
    assert res_b.sequence[0].is_path_verified is False
    assert res_b.sequence[0].path_validation_status == "cyclic"


def test_cyclic_or_unresolved_dependency(memory_db):
    """
    Test 4: Unresolved or cyclic dependency.
    A fastener head is trapped directly beneath an overhang on a stationary bracket.
    The fastener cannot be extracted along +Z because the bracket obstructs its head,
    while the bracket cannot be disassembled until the fastener is removed.
    The motion validation must mark the trapped fastener step as unverified/collision_detected,
    and prevent sequence status from claiming physical validation.
    """
    db = memory_db
    asm = Assembly(filename="cyclic_test.step", sha256="cyclic_sha", status="ready")
    db.add(asm)
    db.commit()

    # Trapped bolt at (0, 0, 10)
    bolt_sh = cq.Workplane().box(10, 10, 20).val().translate((0, 0, 10))
    c_bolt = Component(
        assembly_id=asm.id, cad_entity_id="c_bolt", name="Trapped_Bolt", is_leaf=1,
        bb_xmin=-5, bb_xmax=5, bb_ymin=-5, bb_ymax=5, bb_zmin=0, bb_zmax=20,
    )
    db.add(c_bolt)

    # Overhanging bracket roof directly above the bolt at z = 25..35
    bracket_roof = cq.Workplane().box(40, 40, 10).val().translate((0, 0, 30))
    c_bracket = Component(
        assembly_id=asm.id, cad_entity_id="c_bracket", name="Overhanging_Bracket", is_leaf=1,
        bb_xmin=-20, bb_xmax=20, bb_ymin=-20, bb_ymax=20, bb_zmin=25, bb_zmax=35,
    )
    db.add(c_bracket)
    db.commit()

    _SHAPE_CACHE[f"{asm.id}:{asm.sha256}"] = {"c_bolt": bolt_sh, "c_bracket": bracket_roof}

    graph = DisassemblyGraph(
        assembly_id=asm.id,
        sequence=[
            DisassemblyStep(
                step_number=1,
                component_id=c_bolt.id,
                component_name="Trapped_Bolt",
                cad_entity_id="c_bolt",
                action="remove_fastener",
                removal_direction="+Z",
                prerequisites=["Overhanging_Bracket"],  # Circular prerequisite: bracket blocks bolt
            ),
            DisassemblyStep(
                step_number=2,
                component_id=c_bracket.id,
                component_name="Overhanging_Bracket",
                cad_entity_id="c_bracket",
                action="open_cover",
                removal_direction="+Z",
                prerequisites=["Trapped_Bolt"],
            ),
        ],
        total_steps=2,
        sequence_status="cycle_detected",
    )

    res = validate_disassembly_motion_paths(asm.id, db, graph)

    assert res.is_physically_verified is False
    assert res.sequence_status == "cycle_detected"
    assert res.sequence[0].is_path_verified is False
    assert res.sequence[0].path_validation_status == "cyclic"
    assert res.unverified_steps_count >= 1
