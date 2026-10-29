"""
Performance Benchmarking & Golden Snapshot Harness.
Measures execution time and OpenCASCADE operation counters stage-by-stage:
- BRepAlgoAPI_Common.Build (exact solid-solid boolean intersections)
- BRepExtrema_DistShapeShape.Perform (exact B-Rep distance queries)
- IntCurvesFace_ShapeIntersector.Perform (ray-casting access queries)

Outputs:
- backend/tests/perf/perf_baseline_<fixture>.json (Stage timings and call counts)
- backend/tests/golden/<fixture>_golden.json (Golden analysis outputs for regression assertion)
"""
from __future__ import annotations

import argparse
import json
import logging
import math
import sys
import time
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

# Add backend root to path
backend_dir = Path(__file__).resolve().parent.parent.parent
if str(backend_dir) not in sys.path:
    sys.path.insert(0, str(backend_dir))

from app.database import Base
from app.models.assembly import Assembly, Component
from app.schemas.serviceability import (
    AssemblyServiceabilityReport,
    ClearanceMeasurement,
    ComponentObstructionReport,
    DisassemblyGraph,
)
from app.services.cad_importer import import_step_file
from app.services.geometry_service import (
    analyze_clearances,
    analyze_component_obstructions,
    build_disassembly_graph,
    compute_serviceability_scoring,
    get_assembly_shapes,
)

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("perf_harness")

# ── Dynamic OpenCASCADE Call Counters ──
OCC_COUNTERS = {
    "brep_common_calls": 0,
    "brep_extrema_calls": 0,
    "ray_intersector_calls": 0,
}

_HOOKS_INSTALLED = False

def install_occ_hooks():
    global _HOOKS_INSTALLED
    if _HOOKS_INSTALLED:
        return
    try:
        from OCP.BRepAlgoAPI import BRepAlgoAPI_Common
        from OCP.BRepExtrema import BRepExtrema_DistShapeShape
        from OCP.IntCurvesFace import IntCurvesFace_ShapeIntersector

        orig_common_build = BRepAlgoAPI_Common.Build
        def tracked_common_build(self, *args, **kwargs):
            OCC_COUNTERS["brep_common_calls"] += 1
            return orig_common_build(self, *args, **kwargs)

        orig_extrema_perform = BRepExtrema_DistShapeShape.Perform
        def tracked_extrema_perform(self, *args, **kwargs):
            OCC_COUNTERS["brep_extrema_calls"] += 1
            return orig_extrema_perform(self, *args, **kwargs)

        orig_ray_perform = IntCurvesFace_ShapeIntersector.Perform
        def tracked_ray_perform(self, *args, **kwargs):
            OCC_COUNTERS["ray_intersector_calls"] += 1
            return orig_ray_perform(self, *args, **kwargs)

        BRepAlgoAPI_Common.Build = tracked_common_build
        BRepExtrema_DistShapeShape.Perform = tracked_extrema_perform
        IntCurvesFace_ShapeIntersector.Perform = tracked_ray_perform
        _HOOKS_INSTALLED = True
        logger.info("OpenCASCADE performance tracking hooks installed successfully.")
    except Exception as e:
        logger.warning(f"Could not install OpenCASCADE hooks: {e}")

@contextmanager
def stage_tracker(stage_name: str):
    """Context manager to measure elapsed time and OpenCASCADE call deltas."""
    install_occ_hooks()
    c_start = dict(OCC_COUNTERS)
    t_start = time.perf_counter()
    metrics = {}
    try:
        yield metrics
    finally:
        t_elapsed = time.perf_counter() - t_start
        c_delta = {k: OCC_COUNTERS[k] - c_start[k] for k in OCC_COUNTERS}
        metrics["stage"] = stage_name
        metrics["duration_seconds"] = round(t_elapsed, 4)
        metrics.update(c_delta)


def setup_fixture_db(step_path: Path) -> Tuple[Session, int, int]:
    """Import a STEP file into an isolated in-memory SQLite database and return (db, assembly_id, leaf_count)."""
    assert step_path.exists(), f"STEP file not found: {step_path}"
    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False})
    SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    Base.metadata.create_all(bind=engine)
    db = SessionLocal()

    # Import STEP
    import_res = import_step_file(step_path)
    assert import_res.success, f"Import failed for {step_path}: {import_res.error}"

    # Compute sha256
    import hashlib
    sha256 = hashlib.sha256(step_path.read_bytes()).hexdigest()

    asm = Assembly(
        filename=step_path.name,
        sha256=sha256,
        status="ready",
        importer_version=import_res.importer_used,
    )
    db.add(asm)
    db.flush()

    for c in import_res.components:
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

    leaf_count = db.query(Component).filter(Component.assembly_id == asm.id, Component.is_leaf == 1).count()
    return db, asm.id, leaf_count


def run_benchmark_and_snapshot(
    fixture_name: str,
    step_path: Path,
    out_perf_dir: Path,
    out_golden_dir: Path,
) -> Dict[str, Any]:
    """Execute all pipeline stages, record metrics, and write golden snapshot."""
    logger.info(f"=== Starting benchmark for fixture: {fixture_name} ({step_path.name}) ===")
    install_occ_hooks()
    t_suite_start = time.perf_counter()

    db, assembly_id, leaf_count = setup_fixture_db(step_path)
    logger.info(f"Fixture loaded: {leaf_count} leaf components.")

    stage_metrics = []

    # ── Stage 1: Shape Load & Transform ──
    with stage_tracker("1_shape_load") as m1:
        shapes = get_assembly_shapes(assembly_id, db)
    stage_metrics.append(m1)
    logger.info(f"Stage 1 (Shape Load): {m1['duration_seconds']}s, shapes loaded: {len(shapes)}")

    # ── Stage 2: Pairwise Clearances ──
    with stage_tracker("2_clearances") as m2:
        clearances = analyze_clearances(assembly_id, db, min_threshold_mm=3.0)
    stage_metrics.append(m2)
    logger.info(f"Stage 2 (Clearances): {m2['duration_seconds']}s, pairs tested: {len(clearances)}")

    # ── Stage 3: Per-Component Obstruction Ray Casting ──
    leaf_comps = db.query(Component).filter(Component.assembly_id == assembly_id, Component.is_leaf == 1).all()
    component_obstructions: Dict[int, ComponentObstructionReport] = {}
    with stage_tracker("3_obstruction_analysis") as m3:
        for c in leaf_comps:
            obs = analyze_component_obstructions(assembly_id, c.id, db)
            component_obstructions[c.id] = obs
    stage_metrics.append(m3)
    logger.info(f"Stage 3 (Obstructions): {m3['duration_seconds']}s for {len(leaf_comps)} parts")

    # ── Stage 4: Disassembly Dependency Graph & State-Space Search ──
    with stage_tracker("4_disassembly_graph") as m4:
        dep_graph = build_disassembly_graph(assembly_id, db)
    stage_metrics.append(m4)
    logger.info(
        f"Stage 4 (Disassembly Graph): {m4['duration_seconds']}s, "
        f"steps: {len(dep_graph.sequence)}, common calls: {m4['brep_common_calls']}"
    )

    # ── Stage 5: Full Serviceability Scoring ──
    with stage_tracker("5_serviceability_scoring") as m5:
        score_report = compute_serviceability_scoring(assembly_id, db, {"min_clearance_mm": 3.0})
    stage_metrics.append(m5)
    logger.info(f"Stage 5 (Serviceability Scoring): {m5['duration_seconds']}s, score: {score_report.overall_score}")

    total_duration = round(time.perf_counter() - t_suite_start, 4)

    # Compile Summary
    summary = {
        "fixture_name": fixture_name,
        "filename": step_path.name,
        "leaf_components_count": leaf_count,
        "total_duration_seconds": total_duration,
        "stages": stage_metrics,
        "total_occ_counters": {
            "brep_common_calls": sum(s["brep_common_calls"] for s in stage_metrics),
            "brep_extrema_calls": sum(s["brep_extrema_calls"] for s in stage_metrics),
            "ray_intersector_calls": sum(s["ray_intersector_calls"] for s in stage_metrics),
        },
    }

    # Write Performance JSON
    out_perf_dir.mkdir(parents=True, exist_ok=True)
    perf_file = out_perf_dir / f"baseline_{fixture_name}.json"
    with open(perf_file, "w", encoding="utf-8") as f:
        json.dump(summary, f, indent=2)
    logger.info(f"Performance baseline written to {perf_file}")

    # Compile Golden Reference Snapshot
    golden_data = {
        "fixture_name": fixture_name,
        "leaf_components_count": leaf_count,
        "serviceability_report": score_report.model_dump(mode="json"),
        "clearances": [c.model_dump(mode="json") for c in clearances],
        "component_obstructions": {
            str(cid): rep.model_dump(mode="json") for cid, rep in component_obstructions.items()
        },
        "disassembly_graph": dep_graph.model_dump(mode="json"),
    }

    out_golden_dir.mkdir(parents=True, exist_ok=True)
    golden_file = out_golden_dir / f"{fixture_name}_golden.json"
    with open(golden_file, "w", encoding="utf-8") as f:
        json.dump(golden_data, f, indent=2)
    logger.info(f"Golden snapshot written to {golden_file}")

    db.close()
    return summary


def main():
    parser = argparse.ArgumentParser(description="Performance Harness & Golden Snapshot Runner")
    parser.add_argument("--fixture", choices=["gearbox", "blind", "grid200", "all"], default="all")
    args = parser.parse_args()

    fixtures = {
        "gearbox": backend_dir / "test_data" / "gearbox_assembly.step",
        "blind": backend_dir / "test_data" / "blind_serviceability_test.step",
        "grid200": backend_dir / "test_data" / "grid_200_assembly.step",
    }

    perf_dir = backend_dir / "tests" / "perf"
    golden_dir = backend_dir / "tests" / "golden"

    to_run = list(fixtures.keys()) if args.fixture == "all" else [args.fixture]

    all_summaries = {}
    for name in to_run:
        step_path = fixtures[name]
        if not step_path.exists():
            if name == "grid200":
                from test_data.generate_200_part_assembly import generate_200_part_assembly
                generate_200_part_assembly(step_path)
            else:
                logger.error(f"STEP file missing for {name}: {step_path}")
                continue
        all_summaries[name] = run_benchmark_and_snapshot(name, step_path, perf_dir, golden_dir)

    print("\n================== BASELINE SUMMARY ==================")
    for name, s in all_summaries.items():
        print(f"Fixture: {name} ({s['leaf_components_count']} parts)")
        for st in s["stages"]:
            print(f"  {st['stage']}: {st['duration_seconds']}s (Common: {st['brep_common_calls']}, Extrema: {st['brep_extrema_calls']}, Rays: {st['ray_intersector_calls']})")
        print(f"  TOTAL DURATION: {s['total_duration_seconds']}s")
        print(f"  TOTAL CALLS: Common={s['total_occ_counters']['brep_common_calls']}, Extrema={s['total_occ_counters']['brep_extrema_calls']}, Rays={s['total_occ_counters']['ray_intersector_calls']}\n")

if __name__ == "__main__":
    main()
