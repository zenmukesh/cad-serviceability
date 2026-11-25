# CAD Serviceability Assessment System Architecture

## Overview
This platform automates serviceability analysis for complex 3D CAD assemblies imported from STEP files (ISO-10303-21). It calculates clearance, collision, multi-directional access paths, disassembly sequences, and explainable serviceability scores.

## Architecture Layers

```
+-------------------------------------------------------+
|                   React 18 Frontend                   |
|  - Three.js / @react-three/fiber Canvas               |
|  - Multi-Axis Section Gizmo, ViewCube, Freedom Sphere |
|  - Zustand Store with Single-Flight State             |
|  - Revision Comparison & Disassembly Planner View     |
+-------------------------------------------------------+
                           |
                     HTTP / JSON
                           |
+-------------------------------------------------------+
|                    FastAPI Backend                    |
|  - Lifespan application lifecycle                     |
|  - Asynchronous background analysis queue (202 / poll)|
|  - Dual-tier caching (In-memory LRU + Persistent DB)  |
|  - Streaming ISO-10303-21 upload pipeline             |
+-------------------------------------------------------+
                           |
+-------------------------------------------------------+
|               CAD Geometric Engine (OCP)              |
|  - BRepExtrema minimum distance calculation           |
|  - Analytical line-surface intersection ray casting   |
|  - BRepAlgoAPI_Common volumetric interference checks  |
|  - Swept-volume continuous collision verification     |
+-------------------------------------------------------+
```

## Data Flow & Optimization Strategy
1. **Import & Ingestion:** STEP files are streamed to disk and checked for format markers. Shapes are parsed into OpenCASCADE BRep solids.
2. **Dual-Tier Cache:** An in-memory thread-safe LRU cache holds up to 4 active assemblies for sub-millisecond retrieval. A compressed SQLite database persists completed analysis bundles across server restarts.
3. **Unified Single-Flight Pipeline:** When a serviceability assessment is initiated, intermediate geometric artifacts (clearances, obstruction envelopes, and disassembly graphs) are generated once and bundled into scoring, eliminating redundant ray casting and boolean operations.
4. **Execution Isolation:** CAD kernel calculations execute in a worker process, preventing OpenCASCADE operations from blocking the async FastAPI event loop.

---

## Golden Regression Snapshots & Benchmarks

The regression test suite (`backend/tests/golden/test_golden_verification.py`) verifies CAD serviceability calculations against reference baselines to prevent mathematical drift:
- Minimum distance calculations within $\pm 0.05\text{ mm}$
- Extraction vectors within $\pm 1.0^\circ$
- Disassembly topological step identity and path verification flags
- Serviceability scoring and rating compliance

### Golden Snapshot Artifacts (`backend/tests/golden/`)
- `gearbox_golden.json` (~1.1 MB): 19-part production industrial gearbox fixture with complex curved housings, gears, fasteners, and dipstick interference.
- `blind_golden.json` (~875 KB): Benchmark assembly testing tool access in obstructed cavities and blind holes.
- `grid200_golden.json` (~18.2 MB): Full 200-part synthetic benchmark (baseplate with 199 bolts/blocks) used during Phase 0 baseline performance characterization. Excluded from per-commit CI runs due to cold OpenCASCADE boolean compute time (~60 min), but preserved for algorithm scale validation.

### Snapshot Regeneration Procedure
To regenerate reference snapshots when intentional algorithm improvements are introduced:
```bash
cd backend
python -m tests.golden.generate_golden_snapshots --fixture all
pytest tests/golden/test_golden_verification.py -v
```
