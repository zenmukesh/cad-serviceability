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
