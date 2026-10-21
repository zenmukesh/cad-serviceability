# AI-Assisted CAD-Based Serviceability Assessment System

A professional, engineering-grade application that imports mechanical CAD assemblies (STEP format), analyzes geometric serviceability (component obstruction, clearances, tool approach directions, disassembly dependency graphs), and provides explainable serviceability scoring and recommendations.

Built as a serious B.Tech Mechanical Engineering / research-grade platform.

---

## Architecture Overview

```
cad-serviceability/
├── backend/
│   ├── app/
│   │   ├── main.py              # FastAPI app & CORS configuration
│   │   ├── config.py            # Pydantic Settings
│   │   ├── database.py          # SQLAlchemy SQLite DB session
│   │   ├── models/
│   │   │   └── assembly.py      # Assembly & Component ORM models
│   │   ├── schemas/
│   │   │   └── assembly.py      # Pydantic validation schemas
│   │   ├── routers/
│   │   │   ├── upload.py        # STEP file upload & async processing pipeline
│   │   │   └── assembly.py      # Assembly querying, component hierarchy & geometry
│   │   ├── services/
│   │   │   ├── cad_importer.py  # STEP import using CadQuery / OpenCASCADE kernel
│   │   │   └── tessellator.py   # BRep to triangle mesh conversion with normal repair
│   │   └── utils/
│   │       ├── hash.py          # Cryptographic SHA-256 for file traceability
│   │       └── version_info.py  # Dependency version recording for data integrity
│   ├── tests/
│   │   ├── conftest.py          # Pytest fixtures & synthetic shape generators
│   │   ├── test_import.py       # STEP import verification tests
│   │   ├── test_bounding_box.py # Geometric measurement accuracy tests
│   │   └── test_api.py          # Full FastAPI endpoint integration suite
│   ├── test_data/
│   │   └── generate_test_step.py # Generates parametric STEP test assembly fixture
│   ├── requirements.txt
│   └── pytest.ini
│
├── frontend/
│   ├── src/
│   │   ├── api/
│   │   │   └── client.ts        # Axios client with upload & polling helpers
│   │   ├── components/
│   │   │   ├── common/
│   │   │   │   └── ErrorBanner.tsx
│   │   │   ├── panels/
│   │   │   │   ├── ComponentTree.tsx    # Hierarchy, isolation & visibility toggle
│   │   │   │   └── PropertiesPanel.tsx  # Volume, Area, Bounding Box, editable labels
│   │   │   ├── upload/
│   │   │   │   └── UploadZone.tsx       # Drag-and-drop STEP uploader with progress
│   │   │   └── viewer/
│   │   │       ├── AssemblyViewer.tsx   # Three.js / React Three Fiber CAD viewer
│   │   │       └── ViewerControls.tsx   # Orbit, Pan, Zoom, Fit-to-view, Reset, Grid
│   │   ├── store/
│   │   │   └── assemblyStore.ts # Zustand reactive state
│   │   ├── types/
│   │   │   └── assembly.ts      # TypeScript interfaces
│   │   ├── App.tsx              # Main engineering dashboard
│   │   └── main.tsx
│   ├── package.json
│   └── vite.config.ts
└── README.md
```

---

## Milestone 1 Implemented Features

1. **True CAD Kernel Integration**:
   - Uses **CadQuery 2.4.0** with OpenCASCADE geometry kernel (`cadquery-ocp`).
   - Direct extraction of accurate mathematical solids, bounding boxes, volumes (in $\text{mm}^3$), and surface areas ($\text{mm}^2$).
   - Real tessellation via CadQuery/OpenCASCADE surface meshing with `trimesh` vertex normal calculation and repair.

2. **Backend API (FastAPI)**:
   - `POST /api/upload`: Accepts `.step`/`.stp` files, generates cryptographic SHA-256 hash, and triggers background processing.
   - `GET /api/assemblies`: Lists all imported assemblies with component counts.
   - `GET /api/assemblies/{id}`: Detailed assembly metadata, software versions, and status.
   - `GET /api/assemblies/{id}/components`: Full component tree with geometric bounding boxes.
   - `GET /api/geometry/{component_id}`: Tessellated mesh buffers (vertices, faces, normals) for WebGL rendering.
   - `PATCH /api/components/{id}/label`: Supports user-editable component labels to address missing STEP metadata.
   - `GET /api/health`: Health status and software version metadata for traceability.

3. **Engineering 3D CAD Viewer (React + Three.js)**:
   - Built with **React 18**, **Three.js**, **@react-three/fiber**, and **Tailwind CSS**.
   - Interactive orbit, zoom, pan, fit-to-view bounding sphere calculation.
   - Component selection with visual highlighting, double-click selection in 3D canvas.
   - Isolation mode and visibility toggle per component.
   - Component tree with volume and bounding box tooltips.
   - Properties panel displaying exact bounding box, volume, area, CAD entity IDs, and inline editable names.

4. **Automated Testing & Verification**:
   - 29 automated tests passing:
     - 15 FastAPI endpoint integration tests (`test_api.py`).
     - 10 STEP import and component extraction tests (`test_import.py`).
     - 4 Geometric measurement and bounding-box accuracy tests (`test_bounding_box.py`).

---

## Getting Started

### Prerequisites

- **Python 3.10+ / 3.11** (tested on Python 3.11.9)
- **Node.js 18+ / 24+** and **npm**

### Backend Setup

1. Open a terminal in `backend/`:
   ```bash
   cd backend
   pip install -r requirements.txt
   ```

2. Generate the synthetic test assembly (optional, creates `test_data/simple_assembly.step`):
   ```bash
   python test_data/generate_test_step.py
   ```

3. Run the automated test suite:
   ```bash
   python -m pytest tests -v
   ```

4. Start the FastAPI backend server:
   ```bash
   python -m uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload
   ```
   Interactive API docs are available at `http://localhost:8000/api/docs`.

### Frontend Setup

1. Open another terminal in `frontend/`:
   ```bash
   cd frontend
   npm install
   ```

2. Start the Vite development server:
   ```bash
   npm run dev
   ```
   Open `http://localhost:5173` in your browser.

3. Or build for production:
   ```bash
   npm run build
   ```

---

## Technical Limitations & Notes

- **STEP Metadata Limitations**: STEP AP203/AP214 files often do not preserve detailed part hierarchies or Bill of Materials (BOM) properties. The application extracts available solids and identifiers, and provides an inline editing mechanism (`PATCH /api/components/{id}/label`) so engineers can label parts manually.
- **Unit Conventions**: All measurements assume standard CAD millimeters ($\text{mm}$), resulting in volumes in $\text{mm}^3$ and areas in $\text{mm}^2$.

---

## Next Milestone (Milestone 2: Geometric Serviceability Analysis)

- [ ] **Component Obstruction Detection**: Ray-casting and directional collision detection along disassembly vectors ($\pm X, \pm Y, \pm Z$).
- [ ] **Clearance Measurement**: Minimum distance computation between adjacent components.
- [ ] **Tool Approach Analysis**: Verifying accessibility envelopes for standard wrenches, sockets, and screwdrivers.
- [ ] **Disassembly Dependency Graph**: Directed acyclic graph (DAG) identifying which components must be removed before servicing a target component.
- [ ] **Fastener Classification**: Detection and inventory of standard bolts, screws, and clips.
