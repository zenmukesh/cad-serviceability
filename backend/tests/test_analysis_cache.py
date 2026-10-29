"""
Tests for Step 4: Persistent SQLite Cache and In-Memory LRU.
"""
import time
import pytest
from pathlib import Path
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.database import Base, get_db, SessionLocal
from app.main import app
from app.models.assembly import Assembly, Component
from app.services.cad_importer import import_step_file
from app.services.analysis_manager import (
    clear_analysis_cache,
    get_or_compute_analysis_bundle,
    get_cached_bundle,
    _LRU_CACHE,
    ALGORITHM_VERSION,
)


@pytest.fixture
def cache_test_env():
    step_path = Path("test_data/sample_serviceability_assembly.step")
    if not step_path.exists():
        step_path = Path("backend/test_data/sample_serviceability_assembly.step")
    if not step_path.exists():
        pytest.skip("sample_serviceability_assembly.step not found")

    clear_analysis_cache()
    db = SessionLocal()
    res = import_step_file(step_path)
    asm = Assembly(
        filename="sample_serviceability_assembly.step",
        sha256="9218921f7ff3b4752c9732cde3e9cad46db618431276cbf1cfaae578038333aa",
        status="ready",
    )
    db.add(asm)
    db.commit()
    db.refresh(asm)

    saved_asm_id = int(asm.id)
    for c in res.components:
        db.add(Component(
            assembly_id=saved_asm_id,
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
        ))
    db.commit()
    db.close()

    client = TestClient(app)
    yield client, saved_asm_id
    clear_analysis_cache()


def test_persistent_and_lru_cache_behavior(cache_test_env):
    client, asm_id = cache_test_env

    # 1. First cold run: computes analysis
    t0 = time.time()
    resp1 = client.get(f"/api/assemblies/{asm_id}/serviceability")
    t1 = time.time()
    assert resp1.status_code == 200
    cold_duration = t1 - t0

    # 2. Second warm run: served from in-memory LRU cache (< 100 ms)
    t2 = time.time()
    resp2 = client.get(f"/api/assemblies/{asm_id}/serviceability")
    t3 = time.time()
    assert resp2.status_code == 200
    warm_lru_duration = t3 - t2
    assert warm_lru_duration < 0.100  # Served instantly from LRU
    assert resp1.json()["overall_score"] == resp2.json()["overall_score"]

    # 3. Clear in-memory LRU cache to simulate app restart
    _LRU_CACHE.clear()

    # 4. Third run: served from SQLite persistent cache (< 200 ms)
    t4 = time.time()
    resp3 = client.get(f"/api/assemblies/{asm_id}/serviceability")
    t5 = time.time()
    assert resp3.status_code == 200
    warm_sqlite_duration = t5 - t4
    assert warm_sqlite_duration < 0.200  # Deserialized from SQLite without any OpenCASCADE calls
    assert resp1.json()["overall_score"] == resp3.json()["overall_score"]

    # 5. Test clear cache endpoint
    clear_resp = client.post("/api/cache/clear")
    assert clear_resp.status_code == 200
    assert clear_resp.json()["status"] == "ok"

    # Confirm cache is empty
    assert len(_LRU_CACHE) == 0
