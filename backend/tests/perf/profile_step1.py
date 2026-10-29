"""
Step 1 Diagnostic Harness:
1. Simulates real frontend request order against FastAPI app
2. Tracks request timing, endpoint execution timeline, function invocation counters, and OpenCASCADE calls
3. Profiles compute_serviceability_scoring with cProfile to isolate top 10 bottlenecks
"""
from __future__ import annotations

import cProfile
import io
import json
import logging
import pstats
import sys
import time
from pathlib import Path
from typing import Dict, Any, List

# Ensure backend root is on sys.path
BACKEND_DIR = Path(__file__).resolve().parent.parent.parent
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from fastapi.testclient import TestClient
from app.main import app
from app.database import SessionLocal, init_db
from app.models.assembly import Assembly, Component
from app.services.cad_importer import import_step_file
from app.services.geometry_service import compute_serviceability_scoring
from app.utils.perf_tracker import get_call_counts, reset_call_counts
from tests.perf.perf_harness import install_occ_hooks, OCC_COUNTERS

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("step1_diagnostic")


def setup_assembly_in_db(step_path: Path) -> int:
    """Import fixture into DB for TestClient use."""
    init_db()
    db = SessionLocal()
    import hashlib
    sha256 = hashlib.sha256(step_path.read_bytes()).hexdigest()

    existing = db.query(Assembly).filter(Assembly.sha256 == sha256).first()
    if existing:
        asm_id = existing.id
        db.close()
        return asm_id

    res = import_step_file(step_path)
    assert res.success, f"Failed importing {step_path.name}: {res.error}"

    # Copy file to uploads dir if needed
    uploads_dir = Path("uploads")
    uploads_dir.mkdir(parents=True, exist_ok=True)
    target_step = uploads_dir / f"{sha256}.step"
    if not target_step.exists():
        target_step.write_bytes(step_path.read_bytes())

    asm = Assembly(
        filename=step_path.name,
        sha256=sha256,
        status="ready",
        importer_version=res.importer_used,
        total_parts=len(res.components),
    )
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
    asm_id = asm.id
    db.close()
    return asm_id


def run_real_flow_simulation(asm_id: int):
    """Executes requests in exact real frontend sequence."""
    install_occ_hooks()
    client = TestClient(app)

    db = SessionLocal()
    leaf_comps = (
        db.query(Component)
        .filter(Component.assembly_id == asm_id, Component.is_leaf == 1)
        .all()
    )
    # Pick 3 components to simulate user clicking them in the viewport
    c_ids = [c.id for c in leaf_comps[:3]]
    c_names = [c.display_name for c in leaf_comps[:3]]
    db.close()

    flow_steps = [
        ("1. GET serviceability report (auto-fetch on assembly load)", "GET", f"/api/assemblies/{asm_id}/serviceability", None),
        ("2. GET dependency graph (auto-fetch on assembly load)", "GET", f"/api/assemblies/{asm_id}/dependency-graph", None),
        ("3. POST analyze / calculate score (user clicks Calculate Score)", "POST", f"/api/assemblies/{asm_id}/analyze", {"min_clearance_mm": 3.0}),
        ("4. GET dependency graph (re-fetch after Calculate Score)", "GET", f"/api/assemblies/{asm_id}/dependency-graph", None),
        (f"5. Component Click 1 ({c_names[0]}): obstructions", "GET", f"/api/assemblies/{asm_id}/components/{c_ids[0]}/obstructions", None),
        (f"6. Component Click 1 ({c_names[0]}): clearances", "GET", f"/api/assemblies/{asm_id}/components/{c_ids[0]}/clearances", None),
        (f"7. Component Click 2 ({c_names[1]}): obstructions", "GET", f"/api/assemblies/{asm_id}/components/{c_ids[1]}/obstructions", None),
        (f"8. Component Click 2 ({c_names[1]}): clearances", "GET", f"/api/assemblies/{asm_id}/components/{c_ids[1]}/clearances", None),
        (f"9. Component Click 3 ({c_names[2]}): obstructions", "GET", f"/api/assemblies/{asm_id}/components/{c_ids[2]}/obstructions", None),
        (f"10. Component Click 3 ({c_names[2]}): clearances", "GET", f"/api/assemblies/{asm_id}/components/{c_ids[2]}/clearances", None),
    ]

    print("\n" + "="*80)
    print("REAL FRONTEND FLOW TIMELINE & ANALYSIS EXECUTION AUDIT (gearbox_assembly.step)")
    print("="*80)

    reset_call_counts()
    for k in OCC_COUNTERS:
        OCC_COUNTERS[k] = 0

    timeline_results = []
    flow_start = time.perf_counter()

    for desc, method, endpoint, payload in flow_steps:
        step_t0 = time.perf_counter()
        pre_fn_counts = get_call_counts()
        pre_occ = dict(OCC_COUNTERS)

        if method == "GET":
            resp = client.get(endpoint)
        else:
            resp = client.post(endpoint, json=payload or {})

        step_dur = time.perf_counter() - step_t0
        post_fn_counts = get_call_counts()
        post_occ = dict(OCC_COUNTERS)

        delta_fn = {k: post_fn_counts[k] - pre_fn_counts.get(k, 0) for k in post_fn_counts if post_fn_counts[k] > pre_fn_counts.get(k, 0)}
        delta_occ = {k: post_occ[k] - pre_occ[k] for k in post_occ}

        assert resp.status_code == 200, f"Request failed {endpoint}: {resp.status_code} - {resp.text}"

        step_record = {
            "step": desc,
            "method": method,
            "endpoint": endpoint,
            "duration_s": round(step_dur, 4),
            "function_calls": delta_fn,
            "occ_calls": delta_occ,
        }
        timeline_results.append(step_record)

        print(f"\n>> {desc}")
        print(f"   HTTP: {method} {endpoint} -> Status 200 in {step_dur:.3f} s")
        print(f"   Heavy Functions Executed: {delta_fn}")
        print(f"   OpenCASCADE Primitives: Common={delta_occ['brep_common_calls']}, Extrema={delta_occ['brep_extrema_calls']}, Rays={delta_occ['ray_intersector_calls']}")

    total_flow_dur = time.perf_counter() - flow_start
    total_fns = get_call_counts()
    total_occ = dict(OCC_COUNTERS)

    print("\n" + "="*80)
    print(f"FLOW SUMMARY: Total Duration = {total_flow_dur:.2f} s ({total_flow_dur/60.0:.2f} min)")
    print(f"Total Heavy Function Invocations:")
    for fn, count in total_fns.items():
        print(f"  - {fn}: {count} times")
    print(f"Total OpenCASCADE Calls:")
    print(f"  - BRepAlgoAPI_Common (exact boolean solids): {total_occ['brep_common_calls']}")
    print(f"  - BRepExtrema_DistShapeShape (clearance extrema): {total_occ['brep_extrema_calls']}")
    print(f"  - IntCurvesFace_ShapeIntersector (ray casts): {total_occ['ray_intersector_calls']}")
    print("="*80 + "\n")

    return timeline_results, total_fns, total_occ


def run_cprofile_on_scoring(asm_id: int):
    """Profiles compute_serviceability_scoring with cProfile to isolate top 10 cost lines."""
    db = SessionLocal()
    print("\n" + "="*80)
    print("cProfile ANALYSIS: compute_serviceability_scoring (gearbox_assembly.step)")
    print("="*80)

    profiler = cProfile.Profile()
    profiler.enable()
    t0 = time.perf_counter()
    report = compute_serviceability_scoring(asm_id, db, {"min_clearance_mm": 3.0})
    dur = time.perf_counter() - t0
    profiler.disable()
    db.close()

    print(f"Scoring completed in {dur:.3f} s, overall score: {report.overall_score}")

    s = io.StringIO()
    ps = pstats.Stats(profiler, stream=s).sort_stats(pstats.SortKey.CUMULATIVE)
    ps.print_stats(25)
    print("\n--- TOP 25 BY CUMULATIVE TIME ---")
    print(s.getvalue())

    s2 = io.StringIO()
    ps2 = pstats.Stats(profiler, stream=s2).sort_stats(pstats.SortKey.TIME)
    ps2.print_stats(25)
    print("\n--- TOP 25 BY INTERNAL (SELF) TIME ---")
    print(s2.getvalue())


if __name__ == "__main__":
    step_file = BACKEND_DIR / "test_data" / "gearbox_assembly.step"
    assert step_file.exists(), f"Missing {step_file}"

    asm_id = setup_assembly_in_db(step_file)
    timeline, fn_counts, occ_counts = run_real_flow_simulation(asm_id)
    run_cprofile_on_scoring(asm_id)
