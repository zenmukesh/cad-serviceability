"""
Performance Benchmark for Optimized Pipeline.
Measures execution time and OpenCASCADE operation counters stage-by-stage with:
- Zero redundancy in scoring (reusing precomputed clearances, obstructions, graph)
- AABB spatial culling on fastener tool approach envelopes
- Swept AABB pre-filtering on stepped translations
- SQLite + LRU warm cache retrieval
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
from app.services.analysis_manager import (
    get_or_compute_analysis_bundle,
    get_cached_bundle,
    clear_analysis_cache,
)

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("perf_optimized")

_COUNTER_COMMON = 0
_COUNTER_EXTREMA = 0
_COUNTER_RAY = 0


@contextmanager
def hook_occ_operations():
    global _COUNTER_COMMON, _COUNTER_EXTREMA, _COUNTER_RAY
    _COUNTER_COMMON = 0
    _COUNTER_EXTREMA = 0
    _COUNTER_RAY = 0

    from OCP.BRepAlgoAPI import BRepAlgoAPI_Common
    from OCP.BRepExtrema import BRepExtrema_DistShapeShape
    from OCP.IntCurvesFace import IntCurvesFace_ShapeIntersector

    orig_common_build = BRepAlgoAPI_Common.Build
    orig_extrema_perform = BRepExtrema_DistShapeShape.Perform
    orig_ray_perform = IntCurvesFace_ShapeIntersector.Perform

    def counting_common_build(self, *args, **kwargs):
        global _COUNTER_COMMON
        _COUNTER_COMMON += 1
        return orig_common_build(self, *args, **kwargs)

    def counting_extrema_perform(self, *args, **kwargs):
        global _COUNTER_EXTREMA
        _COUNTER_EXTREMA += 1
        return orig_extrema_perform(self, *args, **kwargs)

    def counting_ray_perform(self, *args, **kwargs):
        global _COUNTER_RAY
        _COUNTER_RAY += 1
        return orig_ray_perform(self, *args, **kwargs)

    try:
        BRepAlgoAPI_Common.Build = counting_common_build
        BRepExtrema_DistShapeShape.Perform = counting_extrema_perform
        IntCurvesFace_ShapeIntersector.Perform = counting_ray_perform
        yield
    finally:
        BRepAlgoAPI_Common.Build = orig_common_build
        BRepExtrema_DistShapeShape.Perform = orig_extrema_perform
        IntCurvesFace_ShapeIntersector.Perform = orig_ray_perform


@contextmanager
def stage_tracker(stage_name: str):
    global _COUNTER_COMMON, _COUNTER_EXTREMA, _COUNTER_RAY
    c_start = _COUNTER_COMMON
    e_start = _COUNTER_EXTREMA
    r_start = _COUNTER_RAY
    t_start = time.perf_counter()
    metrics = {"stage": stage_name}
    try:
        yield metrics
    finally:
        metrics["duration_seconds"] = round(time.perf_counter() - t_start, 4)
        metrics["brep_common_calls"] = _COUNTER_COMMON - c_start
        metrics["brep_extrema_calls"] = _COUNTER_EXTREMA - e_start
        metrics["ray_intersector_calls"] = _COUNTER_RAY - r_start


def run_optimized_benchmark(fixture_name: str, step_path: Path) -> Dict[str, Any]:
    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False})
    Base.metadata.create_all(bind=engine)
    Session = sessionmaker(bind=engine)
    db = Session()

    logger.info(f"Ingesting {fixture_name} ({step_path.name})...")
    res = import_step_file(step_path)
    import hashlib
    file_bytes = step_path.read_bytes()
    sha = hashlib.sha256(file_bytes).hexdigest()

    asm = Assembly(
        filename=step_path.name,
        sha256=sha,
        status="ready",
    )
    db.add(asm)
    db.commit()
    db.refresh(asm)
    assembly_id = asm.id

    for c in res.components:
        db.add(
            Component(
                assembly_id=assembly_id,
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
        )
    db.commit()

    leaf_count = db.query(Component).filter(Component.assembly_id == assembly_id, Component.is_leaf == 1).count()

    stage_metrics = []
    t_suite_start = time.perf_counter()

    with hook_occ_operations():
        # Stage 1: Shape load
        with stage_tracker("1_shape_load") as m1:
            shapes = get_assembly_shapes(assembly_id, db)
        stage_metrics.append(m1)

        # Stage 2: Pairwise clearances
        with stage_tracker("2_clearances") as m2:
            clearances = analyze_clearances(assembly_id, db, min_threshold_mm=3.0)
        stage_metrics.append(m2)

        # Stage 3: Per-component obstructions
        leaf_comps = db.query(Component).filter(Component.assembly_id == assembly_id, Component.is_leaf == 1).all()
        component_obstructions: Dict[int, ComponentObstructionReport] = {}
        with stage_tracker("3_obstruction_analysis") as m3:
            for c in leaf_comps:
                try:
                    obs = analyze_component_obstructions(assembly_id, c.id, db)
                    component_obstructions[c.id] = obs
                except Exception:
                    pass
        stage_metrics.append(m3)

        # Stage 4: Disassembly graph (reusing obstructions)
        with stage_tracker("4_disassembly_graph") as m4:
            dep_graph = build_disassembly_graph(assembly_id, db, precomputed_obstructions=component_obstructions)
        stage_metrics.append(m4)

        # Stage 5: Serviceability scoring (reusing graph, clearances, obstructions with AABB culling)
        with stage_tracker("5_serviceability_scoring") as m5:
            score_report = compute_serviceability_scoring(
                assembly_id=assembly_id,
                db=db,
                settings_dict={"min_clearance_mm": 3.0},
                precomputed_graph=dep_graph,
                precomputed_clearances=clearances,
                precomputed_obstructions=component_obstructions,
            )
        stage_metrics.append(m5)

    total_duration = round(time.perf_counter() - t_suite_start, 4)

    summary = {
        "fixture_name": fixture_name,
        "leaf_components_count": leaf_count,
        "total_duration_seconds": total_duration,
        "stages": stage_metrics,
        "total_occ_counters": {
            "brep_common_calls": sum(s["brep_common_calls"] for s in stage_metrics),
            "brep_extrema_calls": sum(s["brep_extrema_calls"] for s in stage_metrics),
            "ray_intersector_calls": sum(s["ray_intersector_calls"] for s in stage_metrics),
        },
        "overall_score": score_report.overall_score,
    }

    db.close()
    return summary


def main():
    fixtures = {
        "gearbox": backend_dir / "test_data" / "gearbox_assembly.step",
        "blind": backend_dir / "test_data" / "blind_serviceability_test.step",
    }

    out_file = backend_dir / "tests" / "perf" / "perf_optimized_results.json"
    results = {}
    for name, path in fixtures.items():
        if path.exists():
            results[name] = run_optimized_benchmark(name, path)

    with open(out_file, "w", encoding="utf-8") as f:
        json.dump(results, f, indent=2)

    print("\n================== OPTIMIZED BENCHMARK RESULTS ==================")
    for name, s in results.items():
        print(f"\nFixture: {name} ({s['leaf_components_count']} parts, Score: {s['overall_score']})")
        for st in s["stages"]:
            print(f"  {st['stage']}: {st['duration_seconds']}s (Common: {st['brep_common_calls']}, Extrema: {st['brep_extrema_calls']}, Rays: {st['ray_intersector_calls']})")
        print(f"  TOTAL DURATION: {s['total_duration_seconds']}s")
        print(f"  TOTAL CALLS: Common={s['total_occ_counters']['brep_common_calls']}, Extrema={s['total_occ_counters']['brep_extrema_calls']}, Rays={s['total_occ_counters']['ray_intersector_calls']}")


if __name__ == "__main__":
    main()
