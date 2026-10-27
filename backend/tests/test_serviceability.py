"""
Tests for Milestone 2: Serviceability Analysis Engine.

Verifies:
- Minimum clearance calculations using OpenCASCADE BRepExtrema
- Obstruction detection and multi-directional access using B-Rep intersector
- Disassembly dependency DAG and sequence generation
- Explainable 0-100 scoring engine with deductions and safety warnings
- API endpoints for serviceability, obstructions, clearances, and dependencies
- Both sample assemblies: sample_serviceability_assembly and sample_gearbox_serviceability
"""
import pytest
from pathlib import Path
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.database import Base, get_db
from app.main import app
from app.models.assembly import Assembly, Component
from app.services.cad_importer import import_step_file
from app.services.geometry_service import (
    analyze_clearances,
    analyze_component_obstructions,
    build_disassembly_graph,
    compute_serviceability_scoring,
)


@pytest.fixture(scope="module")
def test_db():
    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False})
    TestingSession = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    Base.metadata.create_all(bind=engine)
    db = TestingSession()

    def override_get_db():
        try:
            yield db
        finally:
            pass

    app.dependency_overrides[get_db] = override_get_db

    # Ingest sample_serviceability_assembly
    step_path_1 = Path("test_data/sample_serviceability_assembly.step") if Path("test_data/sample_serviceability_assembly.step").exists() else Path("backend/test_data/sample_serviceability_assembly.step")
    res1 = import_step_file(step_path_1)
    a1 = Assembly(
        filename="sample_serviceability_assembly.step",
        sha256="9218921f7ff3b4752c9732cde3e9cad46db618431276cbf1cfaae578038333aa",
        status="ready",
    )
    db.add(a1)
    db.commit()
    db.refresh(a1)

    for c in res1.components:
        comp = Component(
            assembly_id=a1.id,
            cad_entity_id=c.cad_entity_id,
            name=c.name,
            is_leaf=1 if c.is_leaf else 0,
            component_type=c.component_type,
            bb_xmin=c.bb_xmin, bb_xmax=c.bb_xmax,
            bb_ymin=c.bb_ymin, bb_ymax=c.bb_ymax,
            bb_zmin=c.bb_zmin, bb_zmax=c.bb_zmax,
            volume_mm3=c.volume_mm3,
            surface_area_mm2=c.surface_area_mm2,
        )
        db.add(comp)
    db.commit()

    # Ingest sample_gearbox_serviceability
    step_path_2 = Path("test_data/sample_gearbox_serviceability.step") if Path("test_data/sample_gearbox_serviceability.step").exists() else Path("backend/test_data/sample_gearbox_serviceability.step")
    if step_path_2.exists():
        res2 = import_step_file(step_path_2)
        a2 = Assembly(
            filename="sample_gearbox_serviceability.step",
            sha256="afd686a6c0963b02f4c5a92305152cff614cffa6b2c27e0104cd1971182de282",
            status="ready",
        )
        db.add(a2)
        db.commit()
        db.refresh(a2)

        for c in res2.components:
            comp = Component(
                assembly_id=a2.id,
                cad_entity_id=c.cad_entity_id,
                name=c.name,
                is_leaf=1 if c.is_leaf else 0,
                component_type=c.component_type,
                bb_xmin=c.bb_xmin, bb_xmax=c.bb_xmax,
                bb_ymin=c.bb_ymin, bb_ymax=c.bb_ymax,
                bb_zmin=c.bb_zmin, bb_zmax=c.bb_zmax,
                volume_mm3=c.volume_mm3,
                surface_area_mm2=c.surface_area_mm2,
            )
            db.add(comp)
        db.commit()

    yield db
    db.close()
    app.dependency_overrides.clear()


@pytest.fixture(scope="module")
def client(test_db):
    return TestClient(app)


def test_clearance_calculation(test_db):
    """Verify clearance calculations return valid distances and 3D contact points."""
    a1 = test_db.query(Assembly).filter(Assembly.filename == "sample_serviceability_assembly.step").first()
    assert a1 is not None

    clearances = analyze_clearances(a1.id, test_db, min_threshold_mm=3.0)
    assert len(clearances) > 0

    for c in clearances:
        assert c.distance_mm >= 0.0
        assert c.point_on_target is not None
        assert c.point_on_neighbor is not None
        assert isinstance(c.is_pass, bool)


def test_obstruction_analysis(test_db):
    """Verify 6 cardinal direction obstruction checks run on actual CAD solids."""
    a1 = test_db.query(Assembly).filter(Assembly.filename == "sample_serviceability_assembly.step").first()
    leaf_comp = test_db.query(Component).filter(Component.assembly_id == a1.id, Component.is_leaf == 1).first()
    assert leaf_comp is not None

    obs = analyze_component_obstructions(a1.id, leaf_comp.id, test_db)
    assert obs.target_component_id == leaf_comp.id
    assert len(obs.directions) == 6
    assert obs.best_direction in ["+X", "-X", "+Y", "-Y", "+Z", "-Z"]
    assert obs.max_free_travel_mm >= 0.0


def test_disassembly_graph_generation(test_db):
    """Verify disassembly DAG and step sequence are generated without cycles."""
    a1 = test_db.query(Assembly).filter(Assembly.filename == "sample_serviceability_assembly.step").first()
    graph = build_disassembly_graph(a1.id, test_db)

    assert graph.total_steps > 0
    assert len(graph.sequence) == graph.total_steps
    step_numbers = [s.step_number for s in graph.sequence]
    assert step_numbers == list(range(1, graph.total_steps + 1))


def test_explainable_scoring(test_db):
    """Verify serviceability scores are in 0-100 range and all deductions have clear descriptions."""
    a1 = test_db.query(Assembly).filter(Assembly.filename == "sample_serviceability_assembly.step").first()
    report = compute_serviceability_scoring(a1.id, test_db)

    assert 0.0 <= report.overall_score <= 100.0
    assert report.overall_rating in ["EXCELLENT", "GOOD", "FAIR", "POOR"]
    assert len(report.component_scores) > 0

    for cs in report.component_scores:
        assert 0.0 <= cs.score <= 100.0
        for d in cs.deductions:
            assert d.penalty_points > 0
            assert len(d.description) > 0
            assert d.criterion in [
                "Access & Obstruction", "Clearance", "Disassembly Effort", "Fastener Complexity"
            ]


def test_api_serviceability_endpoints(client, test_db):
    """Verify API endpoints for serviceability return 200 OK and valid schemas."""
    a1 = test_db.query(Assembly).filter(Assembly.filename == "sample_serviceability_assembly.step").first()

    # GET /serviceability
    res = client.get(f"/api/assemblies/{a1.id}/serviceability")
    assert res.status_code == 200
    data = res.json()
    assert "overall_score" in data
    assert "component_scores" in data

    # POST /analyze
    res_post = client.post(f"/api/assemblies/{a1.id}/analyze", json={"min_clearance_mm": 2.5})
    assert res_post.status_code == 200
    assert res_post.json()["settings"]["min_clearance_mm"] == 2.5

    # GET /clearances
    res_clr = client.get(f"/api/assemblies/{a1.id}/clearances")
    assert res_clr.status_code == 200
    assert isinstance(res_clr.json(), list)

    # GET /dependency-graph
    res_dep = client.get(f"/api/assemblies/{a1.id}/dependency-graph")
    assert res_dep.status_code == 200
    assert "sequence" in res_dep.json()

    # GET component obstruction
    comp = test_db.query(Component).filter(Component.assembly_id == a1.id, Component.is_leaf == 1).first()
    res_obs = client.get(f"/api/assemblies/{a1.id}/components/{comp.id}/obstructions")
    assert res_obs.status_code == 200
    assert "directions" in res_obs.json()


def test_gearbox_assembly_serviceability(test_db):
    """Verify serviceability on the complex sample gearbox assembly if available."""
    a2 = test_db.query(Assembly).filter(Assembly.filename == "sample_gearbox_serviceability.step").first()
    if not a2:
        pytest.skip("Gearbox test file not present")

    report = compute_serviceability_scoring(a2.id, test_db)
    assert 0.0 <= report.overall_score <= 100.0
    assert len(report.component_scores) == 18

    # Fastener detection check
    fastener_scores = [c for c in report.component_scores if "bolt" in c.component_name.lower()]
    assert len(fastener_scores) > 0

    # Dependency sequence check
    graph = build_disassembly_graph(a2.id, test_db)
    assert graph.total_steps == 14  # 10 structural leaf parts + 4 unified physical fastener assemblies
    assert len(graph.nodes) == 18
    assert graph.estimated_fastener_count == 4
