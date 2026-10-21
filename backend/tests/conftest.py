"""
Shared pytest fixtures for the CAD Serviceability backend.
"""
import pytest
from pathlib import Path
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.main import app
from app.database import Base, get_db

TEST_DB_URL = "sqlite:///./test_cad_serviceability.db"


@pytest.fixture(scope="session")
def test_engine():
    engine = create_engine(TEST_DB_URL, connect_args={"check_same_thread": False})
    Base.metadata.create_all(bind=engine)
    yield engine
    Base.metadata.drop_all(bind=engine)


@pytest.fixture(scope="function")
def db_session(test_engine):
    Session = sessionmaker(bind=test_engine)
    session = Session()
    yield session
    session.rollback()
    session.close()


@pytest.fixture(scope="session")
def client(test_engine):
    """FastAPI test client using an in-memory test database."""
    Session = sessionmaker(bind=test_engine)

    def override_get_db():
        db = Session()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[get_db] = override_get_db
    with TestClient(app) as c:
        yield c
    app.dependency_overrides.clear()


@pytest.fixture(scope="session")
def test_step_path(tmp_path_factory) -> Path:
    """Generate a synthetic STEP file for tests, or return a pre-existing one."""
    # Try to generate via cadquery
    try:
        from test_data.generate_test_step import generate_test_step
        out_path = tmp_path_factory.mktemp("step") / "simple_assembly.step"
        return generate_test_step(out_path)
    except Exception as e:
        pytest.skip(f"Could not generate test STEP file: {e}")


@pytest.fixture(scope="session")
def simple_box_step(tmp_path_factory) -> Path:
    """Generate a single-body box STEP file for minimal unit tests."""
    try:
        import cadquery as cq
        out_path = tmp_path_factory.mktemp("step") / "single_box.step"
        box = cq.Workplane("XY").box(50, 30, 20)
        cq.exporters.export(box, str(out_path))
        return out_path
    except Exception as e:
        pytest.skip(f"cadquery not available: {e}")
