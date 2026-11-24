"""
CAD Serviceability Assessment System: Prewarm Script
Pre-analyzes bundled sample assemblies and populates the SQLite persistent cache.
"""
from __future__ import annotations

import logging
import sys
import time
from pathlib import Path

# Ensure backend root is in sys.path
backend_dir = Path(__file__).resolve().parent.parent.parent
if str(backend_dir) not in sys.path:
    sys.path.insert(0, str(backend_dir))

from app.database import SessionLocal, init_db
from app.models.assembly import Assembly, Component
from app.services.cad_importer import import_step_file
from app.services.analysis_manager import (
    get_cached_bundle,
    _run_single_analysis_sync,
    _save_to_sqlite,
    make_cache_keys,
    ALGORITHM_VERSION,
)
from app.utils.hash import sha256_file

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("prewarm")


def prewarm_all(min_clearance_mm: float = 3.0):
    logger.info("Initializing database and prewarming sample assemblies...")
    init_db()
    db = SessionLocal()

    test_data_dir = backend_dir / "test_data"
    step_files = sorted(test_data_dir.glob("*.step"))

    if not step_files:
        logger.warning(f"No STEP files found in {test_data_dir}")
        return

    logger.info(f"Found {len(step_files)} sample STEP files to prewarm: {[f.name for f in step_files]}")

    for step_file in step_files:
        # Skip 200-part synthetic stress benchmarks to preserve fast runtime
        if "grid_200" in step_file.name or "200" in step_file.name:
            logger.info(f"[SKIPPED] {step_file.name} (200-part benchmark excluded from prewarm)")
            continue

        t0 = time.time()
        file_hash = sha256_file(step_file)

        # Check if already cached
        cached = get_cached_bundle(file_hash, min_clearance_mm)
        if cached:
            logger.info(f"[ALREADY CACHED] {step_file.name} (SHA: {file_hash[:8]}...) - Score: {cached.report.overall_score:.1f}")
            continue

        # Check if assembly exists in DB
        assembly = db.query(Assembly).filter(Assembly.sha256 == file_hash).first()
        if not assembly:
            logger.info(f"Importing {step_file.name} into database...")
            import_res = import_step_file(step_file)
            if not import_res.success:
                logger.error(f"Failed importing {step_file.name}: {import_res.error}")
                continue

            assembly = Assembly(
                filename=step_file.name,
                sha256=file_hash,
                status="ready",
                revision_label="Prewarmed Sample",
            )
            db.add(assembly)
            db.commit()
            db.refresh(assembly)

            import json
            for comp_data in import_res.components:
                mesh_json = ""
                if comp_data.mesh and comp_data.mesh.vertex_count > 0:
                    mesh_json = json.dumps({
                        "vertices": comp_data.mesh.vertices,
                        "faces": comp_data.mesh.faces,
                        "normals": comp_data.mesh.normals,
                        "vertex_count": comp_data.mesh.vertex_count,
                        "face_count": comp_data.mesh.face_count,
                    })

                c = Component(
                    assembly_id=assembly.id,
                    cad_entity_id=comp_data.cad_entity_id,
                    name=comp_data.name,
                    parent_cad_id=comp_data.parent_cad_id,
                    depth=comp_data.depth,
                    is_leaf=1 if comp_data.is_leaf else 0,
                    bb_xmin=comp_data.bb_xmin,
                    bb_xmax=comp_data.bb_xmax,
                    bb_ymin=comp_data.bb_ymin,
                    bb_ymax=comp_data.bb_ymax,
                    bb_zmin=comp_data.bb_zmin,
                    bb_zmax=comp_data.bb_zmax,
                    volume_mm3=comp_data.volume_mm3,
                    surface_area_mm2=comp_data.surface_area_mm2,
                    placement_matrix=json.dumps(comp_data.placement_matrix),
                    mesh_json=mesh_json,
                )
                db.add(c)
            db.commit()

        logger.info(f"Computing unified serviceability analysis for {step_file.name} (ID: {assembly.id})...")
        bundle = _run_single_analysis_sync(assembly.id, min_clearance_mm)
        cache_key, params_hash = make_cache_keys(assembly.sha256, min_clearance_mm)
        _save_to_sqlite(cache_key, assembly.sha256, params_hash, bundle)

        elapsed = time.time() - t0
        logger.info(f"[PREWARMED] {step_file.name} in {elapsed:.1f}s - Score: {bundle.report.overall_score:.1f} - Cached key: {cache_key[:12]}...")

    db.close()
    logger.info("Prewarm complete! All sample assemblies are persistently cached.")


if __name__ == "__main__":
    prewarm_all()
