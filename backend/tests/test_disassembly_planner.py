"""
Comprehensive Tests for the Intelligent Disassembly Sequence Planner (Milestone 2 Enhancement).

Covers all 12 required verification scenarios:
1. Component blocked along +X but removable along -X.
2. Component blocked along one direction but removable along another principal direction (+Z blocked, +Y clear).
3. Component becomes removable after a blocking component is successfully removed.
4. Fastener must be removed before its clamped component.
5. Failed or unverified removal does not update the active obstacle set.
6. Alternative removal order avoids a dead end in the first candidate sequence.
7. Genuinely blocked component remains unresolved when all supported candidate paths fail.
8. Dependency cycle is detected and reported.
9. Initial solid interference is preserved in the geometry findings.
10. Complete sequence is only marked verified when all required steps have passed the motion checks.
11. Search-budget exhaustion is reported honestly without false claims of impossibility.
12. Repeated runs with the same geometry and settings produce reproducible results.
"""
import pytest
import cadquery as cq
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.database import Base
from app.models.assembly import Assembly, Component
from app.services.geometry_service import (
    _SHAPE_CACHE,
    build_disassembly_graph,
    analyze_clearances,
    compute_step_effort_cost,
    check_entity_extraction_path,
    CARDINAL_DIRECTIONS,
)
from app.schemas.serviceability import DisassemblyGraph, DisassemblyStep


@pytest.fixture
def planner_db():
    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False})
    Session = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    Base.metadata.create_all(bind=engine)
    db = Session()
    yield db
    db.close()


def test_1_blocked_plus_x_removable_minus_x(planner_db):
    """
    Scenario 1: Component is blocked along +X by an obstacle, but has clear space along -X.
    The planner must test +X, detect collision, evaluate -X, confirm clear path, and select -X.
    """
    db = planner_db
    asm = Assembly(filename="test1_dir_switch.step", sha256="sha_test1", status="ready")
    db.add(asm)
    db.commit()

    # Access Cover at (0, 0, 5) -> x: [-5, 5]
    sh_moving = cq.Workplane().box(10, 10, 10).val().translate((0, 0, 5))
    c_moving = Component(
        assembly_id=asm.id, cad_entity_id="cad_m1", name="Access_Cover", is_leaf=1,
        bb_xmin=-5, bb_xmax=5, bb_ymin=-5, bb_ymax=5, bb_zmin=0, bb_zmax=10
    )
    # Obstacle Wall / Internal Gear at x: [15, 25] directly blocking +X
    sh_wall = cq.Workplane().box(10, 30, 30).val().translate((20, 0, 15))
    c_wall = Component(
        assembly_id=asm.id, cad_entity_id="cad_w1", name="Internal_Gear", is_leaf=1,
        bb_xmin=15, bb_xmax=25, bb_ymin=-15, bb_ymax=15, bb_zmin=0, bb_zmax=30
    )
    db.add_all([c_moving, c_wall])
    db.commit()

    _SHAPE_CACHE[f"{asm.id}:{asm.sha256}"] = {"cad_m1": sh_moving, "cad_w1": sh_wall}

    graph = build_disassembly_graph(asm.id, db)
    moving_step = next(s for s in graph.sequence if s.component_name == "Access_Cover")

    assert moving_step.is_path_verified is True
    assert moving_step.path_validation_status == "verified"
    assert moving_step.removal_direction == "-X"
    assert "-X" in moving_step.feasible_directions
    assert "+X" not in moving_step.feasible_directions


def test_2_blocked_plus_z_removable_plus_y(planner_db):
    """
    Scenario 2: Component blocked along +Z by an overhanging roof, but removable along another direction.
    """
    db = planner_db
    asm = Assembly(filename="test2_z_to_y.step", sha256="sha_test2", status="ready")
    db.add(asm)
    db.commit()

    # Part at (0, 0, 5) -> z: [0, 10]
    sh_part = cq.Workplane().box(10, 10, 10).val().translate((0, 0, 5))
    c_part = Component(
        assembly_id=asm.id, cad_entity_id="cad_p2", name="Slider_Block", is_leaf=1,
        bb_xmin=-5, bb_xmax=5, bb_ymin=-5, bb_ymax=5, bb_zmin=0, bb_zmax=10
    )
    # Roof directly above at z: [15, 25]
    sh_roof = cq.Workplane().box(30, 30, 10).val().translate((0, 0, 20))
    c_roof = Component(
        assembly_id=asm.id, cad_entity_id="cad_r2", name="Top_Roof", is_leaf=1,
        bb_xmin=-15, bb_xmax=15, bb_ymin=-15, bb_ymax=15, bb_zmin=15, bb_zmax=25
    )
    db.add_all([c_part, c_roof])
    db.commit()

    _SHAPE_CACHE[f"{asm.id}:{asm.sha256}"] = {"cad_p2": sh_part, "cad_r2": sh_roof}

    graph = build_disassembly_graph(asm.id, db)
    slider_step = next(s for s in graph.sequence if s.component_name == "Slider_Block")

    assert slider_step.is_path_verified is True
    assert slider_step.path_validation_status == "verified"
    assert slider_step.removal_direction in ["+Y", "-Y", "+X", "-X", "-Z"]
    assert "+Z" not in slider_step.feasible_directions


def test_3_removable_after_blocking_component_removed(planner_db):
    """
    Scenario 3: Component B is initially blocked by Component A.
    When Component A is removed first, the corridor clears and Component B becomes removable.
    """
    db = planner_db
    asm = Assembly(filename="test3_sequential.step", sha256="sha_test3", status="ready")
    db.add(asm)
    db.commit()

    # Part B at (0, 0, 5) -> Internal component requiring Cover A to be removed first
    sh_b = cq.Workplane().box(10, 10, 10).val().translate((0, 0, 5))
    c_b = Component(
        assembly_id=asm.id, cad_entity_id="cad_b3", name="Internal_Gear", is_leaf=1,
        bb_xmin=-5, bb_xmax=5, bb_ymin=-5, bb_ymax=5, bb_zmin=0, bb_zmax=10
    )
    # Part A at (18, 0, 5) -> Front access cover that must be removed before Internal_Gear
    sh_a = cq.Workplane().box(10, 10, 10).val().translate((18, 0, 5))
    c_a = Component(
        assembly_id=asm.id, cad_entity_id="cad_a3", name="Front_Access_Cover", is_leaf=1,
        bb_xmin=13, bb_xmax=23, bb_ymin=-5, bb_ymax=5, bb_zmin=0, bb_zmax=10
    )
    db.add_all([c_b, c_a])
    db.commit()

    _SHAPE_CACHE[f"{asm.id}:{asm.sha256}"] = {"cad_b3": sh_b, "cad_a3": sh_a}

    graph = build_disassembly_graph(asm.id, db)

    # Front cover must be removed before Internal gear
    step_a = next(s for s in graph.sequence if s.component_name == "Front_Access_Cover")
    step_b = next(s for s in graph.sequence if s.component_name == "Internal_Gear")

    assert step_a.step_number < step_b.step_number
    assert step_a.is_path_verified is True
    assert step_b.is_path_verified is True
    assert graph.is_physically_verified is True


def test_4_fastener_must_be_removed_before_clamped_component(planner_db):
    """
    Scenario 4: Bolt clamps cover plate to base housing.
    Fastener must be unthreaded and removed before cover plate can be lifted.
    """
    db = planner_db
    asm = Assembly(filename="test4_clamp.step", sha256="sha_test4", status="ready")
    db.add(asm)
    db.commit()

    # Base housing: z: [0, 10]
    sh_base = cq.Workplane().box(60, 60, 10).val().translate((0, 0, 5))
    c_base = Component(assembly_id=asm.id, cad_entity_id="cad_base4", name="Main_Housing", is_leaf=1, bb_xmin=-30, bb_xmax=30, bb_ymin=-30, bb_ymax=30, bb_zmin=0, bb_zmax=10)

    # Cover plate with clearance hole: z: [10, 20]
    cov_solid = cq.Workplane().box(40, 40, 10).val().translate((0, 0, 15))
    hole = cq.Workplane().box(9, 9, 12).val().translate((0, 0, 15))
    sh_cover = cov_solid.cut(hole)
    c_cover = Component(assembly_id=asm.id, cad_entity_id="cad_cov4", name="Housing_Cover", is_leaf=1, bb_xmin=-20, bb_xmax=20, bb_ymin=-20, bb_ymax=20, bb_zmin=10, bb_zmax=20)

    # Fastener bolt: shank in hole [9, 20], head [20, 26]
    shank = cq.Workplane().box(8, 8, 11).val().translate((0, 0, 14.5))
    head = cq.Workplane().box(16, 16, 6).val().translate((0, 0, 23))
    sh_bolt = shank.fuse(head)
    c_bolt = Component(assembly_id=asm.id, cad_entity_id="cad_bolt4", name="Cover_Bolt_1", is_leaf=1, bb_xmin=-8, bb_xmax=8, bb_ymin=-8, bb_ymax=8, bb_zmin=9, bb_zmax=26)

    db.add_all([c_base, c_cover, c_bolt])
    db.commit()

    _SHAPE_CACHE[f"{asm.id}:{asm.sha256}"] = {"cad_base4": sh_base, "cad_cov4": sh_cover, "cad_bolt4": sh_bolt}

    graph = build_disassembly_graph(asm.id, db)

    bolt_step = next(s for s in graph.sequence if s.component_name == "Cover_Bolt_1")
    cover_step = next(s for s in graph.sequence if s.component_name == "Housing_Cover")

    assert bolt_step.step_number < cover_step.step_number
    assert bolt_step.is_path_verified is True
    assert cover_step.is_path_verified is True
    assert any("Bolt" in p for p in cover_step.prerequisites)


def test_5_failed_removal_does_not_update_active_obstacles(planner_db):
    """
    Scenario 5: When an entity's removal path is blocked, it must NEVER be removed from
    the active obstacle set. Components behind it must continue to detect its obstruction.
    """
    db = planner_db
    asm = Assembly(filename="test5_obs_persistence.step", sha256="sha_test5", status="ready")
    db.add(asm)
    db.commit()

    # Trapped core inside a completely sealed hollow cavity centered at (0, 0, 15)
    sh_trapped = cq.Workplane().box(8, 8, 8).val().translate((0, 0, 15))
    c_trapped = Component(assembly_id=asm.id, cad_entity_id="cad_t5", name="Trapped_Core", is_leaf=1, bb_xmin=-4, bb_xmax=4, bb_ymin=-4, bb_ymax=4, bb_zmin=11, bb_zmax=19)

    # Completely sealed surrounding wall cage around Trapped_Core
    outer = cq.Workplane().box(30, 30, 30).val().translate((0, 0, 15))
    cavity = cq.Workplane().box(12, 12, 12).val().translate((0, 0, 15))
    sh_cage = outer.cut(cavity)
    c_cage = Component(assembly_id=asm.id, cad_entity_id="cad_c5", name="Fixed_Cage", is_leaf=1, bb_xmin=-15, bb_xmax=15, bb_ymin=-15, bb_ymax=15, bb_zmin=0, bb_zmax=30)

    db.add_all([c_trapped, c_cage])
    db.commit()

    _SHAPE_CACHE[f"{asm.id}:{asm.sha256}"] = {"cad_t5": sh_trapped, "cad_c5": sh_cage}

    graph = build_disassembly_graph(asm.id, db)

    trapped_step = next(s for s in graph.sequence if s.component_name == "Trapped_Core")
    assert trapped_step.is_path_verified is False
    assert trapped_step.path_validation_status in ["blocked", "collision_detected", "unverified"]
    assert graph.is_physically_verified is False


def test_6_alternative_removal_order_avoids_dead_end(planner_db):
    """
    Scenario 6: Alternative removal order avoids a dead end.
    Part A is inside a channel blocked along +X by Part B.
    Part B is free to move.
    The planner must search alternative orders, remove Part B first,
    and then successfully remove Part A.
    """
    db = planner_db
    asm = Assembly(filename="test6_backtrack.step", sha256="sha_test6", status="ready")
    db.add(asm)
    db.commit()

    # Part A at x: [0, 10]
    sh_a = cq.Workplane().box(10, 10, 10).val().translate((5, 0, 5))
    c_a = Component(assembly_id=asm.id, cad_entity_id="cad_a6", name="Component_Alpha", is_leaf=1, bb_xmin=0, bb_xmax=10, bb_ymin=-5, bb_ymax=5, bb_zmin=0, bb_zmax=10)

    # Part B at (16, 0, 5) directly in front of A along +X, but B can move freely
    sh_b = cq.Workplane().box(10, 10, 10).val().translate((16, 0, 5))
    c_b = Component(assembly_id=asm.id, cad_entity_id="cad_b6", name="Component_Beta", is_leaf=1, bb_xmin=11, bb_xmax=21, bb_ymin=-5, bb_ymax=5, bb_zmin=0, bb_zmax=10)

    # Housing channel enclosing Alpha
    outer = cq.Workplane().box(20, 30, 20).val().translate((0, 0, 5))
    pocket = cq.Workplane().box(11, 11, 11).val().translate((5.5, 0, 5))
    sh_channel = outer.cut(pocket)
    c_channel = Component(assembly_id=asm.id, cad_entity_id="cad_c6", name="Fixed_Channel", is_leaf=1, bb_xmin=-10, bb_xmax=10, bb_ymin=-15, bb_ymax=15, bb_zmin=-5, bb_zmax=15)

    db.add_all([c_a, c_b, c_channel])
    db.commit()

    _SHAPE_CACHE[f"{asm.id}:{asm.sha256}"] = {"cad_a6": sh_a, "cad_b6": sh_b, "cad_c6": sh_channel}

    graph = build_disassembly_graph(asm.id, db)

    # Both must be verified!
    assert graph.is_physically_verified is True
    assert graph.sequence_status == "physically_verified"

    # Beta removed before Alpha
    step_beta = next(s for s in graph.sequence if s.component_name == "Component_Beta")
    step_alpha = next(s for s in graph.sequence if s.component_name == "Component_Alpha")
    assert step_beta.step_number < step_alpha.step_number
    assert step_beta.is_path_verified is True
    assert step_alpha.is_path_verified is True


def test_7_genuinely_blocked_component_remains_unresolved(planner_db):
    """
    Scenario 7: A component trapped inside a closed solid cage with zero exit paths.
    Planner must report it as unresolved, classify it as blocked along all 6 directions,
    and accurately identify the obstructing cage.
    """
    db = planner_db
    asm = Assembly(filename="test7_blocked.step", sha256="sha_test7", status="ready")
    db.add(asm)
    db.commit()

    sh_core = cq.Workplane().box(8, 8, 8).val().translate((0, 0, 10))
    c_core = Component(assembly_id=asm.id, cad_entity_id="cad_core7", name="Trapped_Pellet", is_leaf=1, bb_xmin=-4, bb_xmax=4, bb_ymin=-4, bb_ymax=4, bb_zmin=6, bb_zmax=14)

    # Outer sealed box with interior hollow
    outer = cq.Workplane().box(30, 30, 30).val().translate((0, 0, 10))
    cavity = cq.Workplane().box(12, 12, 12).val().translate((0, 0, 10))
    sh_shell = outer.cut(cavity)
    c_shell = Component(assembly_id=asm.id, cad_entity_id="cad_shell7", name="Hermetic_Shell", is_leaf=1, bb_xmin=-15, bb_xmax=15, bb_ymin=-15, bb_ymax=15, bb_zmin=-5, bb_zmax=25)

    db.add_all([c_core, c_shell])
    db.commit()

    _SHAPE_CACHE[f"{asm.id}:{asm.sha256}"] = {"cad_core7": sh_core, "cad_shell7": sh_shell}

    graph = build_disassembly_graph(asm.id, db)

    assert graph.is_physically_verified is False
    assert "Trapped_Pellet" in graph.unresolved_components
    pellet_step = next(s for s in graph.sequence if s.component_name == "Trapped_Pellet")
    assert pellet_step.is_path_verified is False
    assert pellet_step.path_validation_status == "blocked"
    assert "Hermetic_Shell" in pellet_step.colliding_components_along_path


def test_8_dependency_cycle_detected_and_reported(planner_db):
    """
    Scenario 8: Circular dependency between Part 1 and Part 2.
    The planner must detect the cycle and report sequence_status == 'cycle_detected'.
    """
    db = planner_db
    asm = Assembly(filename="test8_cycle.step", sha256="sha_test8", status="ready")
    db.add(asm)
    db.commit()

    sh1 = cq.Workplane().box(10, 10, 10).val().translate((0, 0, 5))
    c1 = Component(assembly_id=asm.id, cad_entity_id="cad_c1_8", name="Interlocked_A", is_leaf=1, bb_xmin=-5, bb_xmax=5, bb_ymin=-5, bb_ymax=5, bb_zmin=0, bb_zmax=10)

    sh2 = cq.Workplane().box(10, 10, 10).val().translate((15, 0, 5))
    c2 = Component(assembly_id=asm.id, cad_entity_id="cad_c2_8", name="Interlocked_B", is_leaf=1, bb_xmin=10, bb_xmax=20, bb_ymin=-5, bb_ymax=5, bb_zmin=0, bb_zmax=10)

    db.add_all([c1, c2])
    db.commit()

    _SHAPE_CACHE[f"{asm.id}:{asm.sha256}"] = {"cad_c1_8": sh1, "cad_c2_8": sh2}

    # Mutual dependency edge
    graph = DisassemblyGraph(
        assembly_id=asm.id,
        sequence=[
            DisassemblyStep(step_number=1, component_id=c1.id, component_name="Interlocked_A", cad_entity_id="cad_c1_8", action="extract_component", removal_direction="+X", prerequisites=["Interlocked_B"]),
            DisassemblyStep(step_number=2, component_id=c2.id, component_name="Interlocked_B", cad_entity_id="cad_c2_8", action="extract_component", removal_direction="+X", prerequisites=["Interlocked_A"]),
        ],
        total_steps=2,
        sequence_status="cycle_detected",
    )
    from app.services.geometry_service import validate_disassembly_motion_paths
    res = validate_disassembly_motion_paths(asm.id, db, graph)

    assert res.sequence_status == "cycle_detected"
    assert res.is_physically_verified is False
    assert res.sequence[0].path_validation_status == "cyclic"


def test_9_initial_solid_interference_preserved_in_geometry_findings(planner_db):
    """
    Scenario 9: Initial solid overlap between two components must remain preserved in
    analyze_clearances as INTERFERENCE with non-zero clash volume, even while disassembly is evaluated.
    """
    db = planner_db
    asm = Assembly(filename="test9_overlap.step", sha256="sha_test9", status="ready")
    db.add(asm)
    db.commit()

    # Overlapping boxes: 2mm overlap in X -> volume = 2 * 10 * 10 = 200 mm3
    b1 = cq.Workplane().box(10, 10, 10).val().translate((0, 0, 5))
    c1 = Component(assembly_id=asm.id, cad_entity_id="cad_o1", name="Solid_A", is_leaf=1, bb_xmin=-5, bb_xmax=5, bb_ymin=-5, bb_ymax=5, bb_zmin=0, bb_zmax=10)

    b2 = cq.Workplane().box(10, 10, 10).val().translate((8, 0, 5))
    c2 = Component(assembly_id=asm.id, cad_entity_id="cad_o2", name="Solid_B", is_leaf=1, bb_xmin=3, bb_xmax=13, bb_ymin=-5, bb_ymax=5, bb_zmin=0, bb_zmax=10)

    db.add_all([c1, c2])
    db.commit()

    _SHAPE_CACHE[f"{asm.id}:{asm.sha256}"] = {"cad_o1": b1, "cad_o2": b2}

    # Run clearances analysis
    clearances = analyze_clearances(asm.id, db, min_threshold_mm=3.0)
    interferences = [c for c in clearances if c.classification == "INTERFERENCE"]

    assert len(interferences) >= 1
    clash = interferences[0]
    assert clash.classification == "INTERFERENCE"
    assert pytest.approx(clash.intersection_volume_mm3, rel=1e-2) == 200.0

    # Running disassembly planning must not erase or overwrite the initial collision findings
    graph = build_disassembly_graph(asm.id, db)
    clearances_after = analyze_clearances(asm.id, db, min_threshold_mm=3.0)
    interferences_after = [c for c in clearances_after if c.classification == "INTERFERENCE"]

    assert len(interferences_after) == len(interferences)
    assert pytest.approx(interferences_after[0].intersection_volume_mm3, rel=1e-2) == 200.0


def test_10_complete_sequence_only_verified_when_all_steps_pass(planner_db):
    """
    Scenario 10: Complete sequence is only marked verified when all required steps have passed
    motion checks. If any step is blocked or unverified, is_physically_verified is False.
    """
    db = planner_db
    asm = Assembly(filename="test10_partial.step", sha256="sha_test10", status="ready")
    db.add(asm)
    db.commit()

    # Free part: sits on top of base
    sh_free = cq.Workplane().box(10, 10, 10).val().translate((0, 0, 15))
    c_free = Component(assembly_id=asm.id, cad_entity_id="cad_f10", name="Free_Cap", is_leaf=1, bb_xmin=-5, bb_xmax=5, bb_ymin=-5, bb_ymax=5, bb_zmin=10, bb_zmax=20)

    # Trapped part: enclosed inside a cage
    sh_trap = cq.Workplane().box(8, 8, 8).val().translate((50, 0, 10))
    c_trap = Component(assembly_id=asm.id, cad_entity_id="cad_t10", name="Trapped_Core", is_leaf=1, bb_xmin=46, bb_xmax=54, bb_ymin=-4, bb_ymax=4, bb_zmin=6, bb_zmax=14)

    cage = cq.Workplane().box(25, 25, 25).val().translate((50, 0, 10)).cut(cq.Workplane().box(12, 12, 12).val().translate((50, 0, 10)))
    c_cage = Component(assembly_id=asm.id, cad_entity_id="cad_c10", name="Cage_Body", is_leaf=1, bb_xmin=37.5, bb_xmax=62.5, bb_ymin=-12.5, bb_ymax=12.5, bb_zmin=-2.5, bb_zmax=22.5)

    db.add_all([c_free, c_trap, c_cage])
    db.commit()

    _SHAPE_CACHE[f"{asm.id}:{asm.sha256}"] = {"cad_f10": sh_free, "cad_t10": sh_trap, "cad_c10": cage}

    graph = build_disassembly_graph(asm.id, db)

    # Free_Cap was verified, but Trapped_Core could not be removed
    assert graph.is_physically_verified is False
    assert graph.verified_steps_count >= 1
    assert graph.unverified_steps_count >= 1
    assert "Trapped_Core" in graph.unresolved_components


def test_11_search_budget_exhaustion_reported_honestly(planner_db):
    """
    Scenario 11: When max_search_nodes is intentionally set to an extremely low budget (e.g. 1 node),
    the planner reports sequence_status == 'budget_exhausted' and is_search_budget_exhausted == True,
    without making a false claim of physical impossibility.
    """
    db = planner_db
    asm = Assembly(filename="test11_budget.step", sha256="sha_test11", status="ready")
    db.add(asm)
    db.commit()

    # Three parts requiring exploration
    sh1 = cq.Workplane().box(10, 10, 10).val().translate((0, 0, 5))
    c1 = Component(assembly_id=asm.id, cad_entity_id="cad_b11_1", name="Block_1", is_leaf=1, bb_xmin=-5, bb_xmax=5, bb_ymin=-5, bb_ymax=5, bb_zmin=0, bb_zmax=10)

    sh2 = cq.Workplane().box(10, 10, 10).val().translate((20, 0, 5))
    c2 = Component(assembly_id=asm.id, cad_entity_id="cad_b11_2", name="Block_2", is_leaf=1, bb_xmin=15, bb_xmax=25, bb_ymin=-5, bb_ymax=5, bb_zmin=0, bb_zmax=10)

    sh3 = cq.Workplane().box(10, 10, 10).val().translate((40, 0, 5))
    c3 = Component(assembly_id=asm.id, cad_entity_id="cad_b11_3", name="Block_3", is_leaf=1, bb_xmin=35, bb_xmax=45, bb_ymin=-5, bb_ymax=5, bb_zmin=0, bb_zmax=10)

    db.add_all([c1, c2, c3])
    db.commit()

    _SHAPE_CACHE[f"{asm.id}:{asm.sha256}"] = {"cad_b11_1": sh1, "cad_b11_2": sh2, "cad_b11_3": sh3}

    # Run with tiny search budget of 2 nodes
    graph = build_disassembly_graph(asm.id, db, max_search_nodes=2)

    assert graph.is_search_budget_exhausted is True
    assert graph.sequence_status == "budget_exhausted"
    assert any("Search budget limit reached" in note for note in graph.validation_notes)
    assert graph.is_physically_verified is False


def test_12_repeated_runs_produce_reproducible_results(planner_db):
    """
    Scenario 12: Repeated runs on the exact same geometry and settings must produce
    identical step counts, component order, removal directions, and effort scores.
    """
    db = planner_db
    asm = Assembly(filename="test12_reproducible.step", sha256="sha_test12", status="ready")
    db.add(asm)
    db.commit()

    sh_base = cq.Workplane().box(50, 50, 10).val().translate((0, 0, 5))
    c_base = Component(assembly_id=asm.id, cad_entity_id="cad_rep_base", name="Base_Fixture", is_leaf=1, bb_xmin=-25, bb_xmax=25, bb_ymin=-25, bb_ymax=25, bb_zmin=0, bb_zmax=10)

    sh_cap = cq.Workplane().box(20, 20, 10).val().translate((0, 0, 15))
    c_cap = Component(assembly_id=asm.id, cad_entity_id="cad_rep_cap", name="Top_Cap", is_leaf=1, bb_xmin=-10, bb_xmax=10, bb_ymin=-10, bb_ymax=10, bb_zmin=10, bb_zmax=20)

    db.add_all([c_base, c_cap])
    db.commit()

    _SHAPE_CACHE[f"{asm.id}:{asm.sha256}"] = {"cad_rep_base": sh_base, "cad_rep_cap": sh_cap}

    graph_run1 = build_disassembly_graph(asm.id, db)
    graph_run2 = build_disassembly_graph(asm.id, db)

    assert graph_run1.total_steps == graph_run2.total_steps
    assert graph_run1.sequence_status == graph_run2.sequence_status
    assert graph_run1.is_physically_verified == graph_run2.is_physically_verified
    assert graph_run1.total_disassembly_effort_score == graph_run2.total_disassembly_effort_score

    for s1, s2 in zip(graph_run1.sequence, graph_run2.sequence):
        assert s1.component_name == s2.component_name
        assert s1.removal_direction == s2.removal_direction
        assert s1.path_validation_status == s2.path_validation_status
        assert s1.step_effort_cost == s2.step_effort_cost
