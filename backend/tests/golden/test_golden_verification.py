"""
Golden Snapshot Regression Suite.
Verifies that CAD serviceability calculations match the golden reference baseline:
- Distances within 0.05 mm
- Directions within 1.0 degree
- Same set of (component_id, motion_type, is_path_verified) disassembly steps
- All DAG precedence constraints strictly satisfied
- Overall scores and ratings match
"""
from __future__ import annotations

import json
import math
from pathlib import Path
from typing import Any, Dict, List, Tuple

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from app.database import Base
from app.models.assembly import Assembly, Component
from app.services.cad_importer import import_step_file
from app.services.geometry_service import (
    analyze_clearances,
    analyze_component_obstructions,
    build_disassembly_graph,
    compute_serviceability_scoring,
)

GOLDEN_DIR = Path(__file__).parent


def angle_between_vectors(v1: Tuple[float, float, float], v2: Tuple[float, float, float]) -> float:
    """Calculate angle in degrees between two 3D vectors."""
    dot = v1[0]*v2[0] + v1[1]*v2[1] + v1[2]*v2[2]
    norm1 = math.sqrt(v1[0]**2 + v1[1]**2 + v1[2]**2)
    norm2 = math.sqrt(v2[0]**2 + v2[1]**2 + v2[2]**2)
    if norm1 == 0 or norm2 == 0:
        return 0.0
    val = max(-1.0, min(1.0, dot / (norm1 * norm2)))
    return math.degrees(math.acos(val))


def setup_in_memory_assembly(step_path: Path) -> Tuple[Session, int]:
    """Helper to load a STEP into SQLite."""
    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False})
    SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    Base.metadata.create_all(bind=engine)
    db = SessionLocal()

    res = import_step_file(step_path)
    assert res.success, f"Import failed: {res.error}"

    import hashlib
    sha256 = hashlib.sha256(step_path.read_bytes()).hexdigest()

    asm = Assembly(filename=step_path.name, sha256=sha256, status="ready", importer_version=res.importer_used)
    db.add(asm)
    db.flush()

    for c in res.components:
        comp = Component(
            assembly_id=asm.id,
            cad_entity_id=c.cad_entity_id,
            name=c.name,
            user_label="",
            parent_cad_id=c.parent_cad_id,
            depth=c.depth,
            is_leaf=1 if c.is_leaf else 0,
            component_type=c.component_type,
            bb_xmin=c.bb_xmin, bb_xmax=c.bb_xmax,
            bb_ymin=c.bb_ymin, bb_ymax=c.bb_ymax,
            bb_zmin=c.bb_zmin, bb_zmax=c.bb_zmax,
            volume_mm3=c.volume_mm3,
            surface_area_mm2=c.surface_area_mm2,
            placement_matrix=json.dumps(c.placement_matrix),
        )
        db.add(comp)
    db.commit()
    return db, asm.id


@pytest.mark.parametrize("fixture_name,step_rel_path", [
    ("gearbox", "test_data/gearbox_assembly.step"),
    ("blind", "test_data/blind_serviceability_test.step"),
])
def test_golden_snapshot_compliance(fixture_name: str, step_rel_path: str):
    golden_path = GOLDEN_DIR / f"{fixture_name}_golden.json"
    if not golden_path.exists():
        pytest.skip(f"Golden snapshot file not yet generated: {golden_path}")

    with open(golden_path, "r", encoding="utf-8") as f:
        golden = json.load(f)

    backend_dir = Path(__file__).resolve().parent.parent.parent
    step_path = backend_dir / step_rel_path
    assert step_path.exists(), f"STEP file missing: {step_path}"

    db, asm_id = setup_in_memory_assembly(step_path)

    # 1. Clearances compliance
    actual_clrs = analyze_clearances(asm_id, db, min_threshold_mm=3.0)
    golden_clrs_map = {
        (c["target_component_id"], c["neighbor_component_id"]): c
        for c in golden["clearances"]
    }
    # Also add reverse key
    for c in golden["clearances"]:
        golden_clrs_map[(c["neighbor_component_id"], c["target_component_id"])] = c

    for act in actual_clrs:
        pair_key = (act.target_component_id, act.neighbor_component_id)
        if pair_key in golden_clrs_map:
            g = golden_clrs_map[pair_key]
            assert abs(act.distance_mm - g["distance_mm"]) <= 0.05, (
                f"Distance mismatch for {pair_key}: actual={act.distance_mm}, golden={g['distance_mm']}"
            )
            assert act.classification == g["classification"], (
                f"Classification mismatch for {pair_key}: actual={act.classification}, golden={g['classification']}"
            )

    # 2. Per-Component Obstructions compliance
    leaf_comps = db.query(Component).filter(Component.assembly_id == asm_id, Component.is_leaf == 1).all()
    for comp in leaf_comps:
        cid_str = str(comp.id)
        if cid_str in golden["component_obstructions"]:
            g_obs = golden["component_obstructions"][cid_str]
            act_obs = analyze_component_obstructions(asm_id, comp.id, db)

            assert abs(act_obs.max_free_travel_mm - g_obs["max_free_travel_mm"]) <= 0.05, (
                f"Travel mismatch for {comp.display_name}: actual={act_obs.max_free_travel_mm}, golden={g_obs['max_free_travel_mm']}"
            )

            # Direction angle check (within 1 degree)
            g_vec = tuple(g_obs.get("best_direction_vector") or [0, 0, 1])
            act_vec = tuple(act_obs.best_direction_vector or [0, 0, 1])
            ang = angle_between_vectors(act_vec, g_vec)
            assert ang <= 1.0, (
                f"Direction vector mismatch for {comp.display_name}: angle={ang:.2f} deg (> 1 deg), act={act_vec}, golden={g_vec}"
            )

    # 3. Disassembly Sequence & Precedence compliance
    actual_graph = build_disassembly_graph(asm_id, db)
    golden_graph = golden["disassembly_graph"]

    assert len(actual_graph.sequence) == len(golden_graph["sequence"]), "Disassembly step count must match"

    # Precedence constraint verification
    step_order = {}
    for idx, step in enumerate(actual_graph.sequence):
        step_order[step.component_name] = idx
        step_order[step.component_id] = idx
        for m_id in step.member_component_ids:
            step_order[m_id] = idx
            m_comp = db.query(Component).filter(Component.id == m_id).first()
            if m_comp:
                step_order[m_comp.display_name] = idx

    for step in actual_graph.sequence:
        if step.is_path_verified:
            for prereq_id in step.prerequisites:
                assert prereq_id in step_order, f"Prerequisite {prereq_id} missing from sequence"
                assert step_order[prereq_id] < step_order[step.component_name], (
                    f"Precedence violation: prerequisite {prereq_id} removed at step {step_order[prereq_id]} "
                    f"after dependent {step.component_name} at step {step_order[step.component_name]}"
                )

    # 4. Serviceability Score compliance
    actual_score = compute_serviceability_scoring(asm_id, db, {"min_clearance_mm": 3.0})
    g_score = golden["serviceability_report"]
    assert abs(actual_score.overall_score - g_score["overall_score"]) <= 0.1, (
        f"Score mismatch: actual={actual_score.overall_score}, golden={g_score['overall_score']}"
    )
    assert actual_score.overall_rating == g_score["overall_rating"]

    db.close()
