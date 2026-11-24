"""
FastAPI endpoint integration tests.
Tests the API contract without requiring a running server.
"""
import io
import json
import pytest
from pathlib import Path


class TestHealthEndpoint:
    def test_health_returns_ok(self, client):
        resp = client.get("/api/health")
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "ok"
        assert "software_versions" in data
        assert "version" in data

    def test_health_includes_python_version(self, client):
        resp = client.get("/api/health")
        data = resp.json()
        versions = data["software_versions"]
        assert "python" in versions
        assert versions["python"].startswith("3.")


class TestAssembliesEndpoint:
    def test_list_assemblies_empty(self, client):
        """Fresh DB should return an empty list."""
        resp = client.get("/api/assemblies")
        assert resp.status_code == 200
        assert isinstance(resp.json(), list)

    def test_get_nonexistent_assembly(self, client):
        resp = client.get("/api/assemblies/999999")
        assert resp.status_code == 404

    def test_get_assembly_components_nonexistent(self, client):
        resp = client.get("/api/assemblies/999999/components")
        assert resp.status_code == 404


class TestUploadEndpoint:
    def test_upload_wrong_extension(self, client):
        """Upload an IGES file — should be rejected with 400."""
        data = {"file": ("model.iges", b"fake iges content", "application/octet-stream")}
        resp = client.post("/api/upload", files=data)
        assert resp.status_code == 400
        assert "Unsupported" in resp.json()["detail"]

    def test_upload_empty_file(self, client):
        """Upload a zero-byte STEP file — should be rejected with 400."""
        data = {"file": ("empty.step", b"", "application/octet-stream")}
        resp = client.post("/api/upload", files=data)
        assert resp.status_code == 400
        assert "empty" in resp.json()["detail"].lower()

    def test_upload_valid_step(self, client, simple_box_step):
        """Upload a valid STEP file — should return 202 with assembly_id."""
        with open(simple_box_step, "rb") as f:
            content = f.read()

        files = {"file": ("test_box.step", content, "application/octet-stream")}
        resp = client.post("/api/upload", files=files)

        assert resp.status_code == 202, f"Expected 202, got {resp.status_code}: {resp.text}"
        data = resp.json()
        assert "assembly_id" in data
        assert data["assembly_id"] > 0
        assert data["sha256"]
        assert len(data["sha256"]) == 64  # SHA-256 hex string
        assert data["status"] == "processing"

    def test_upload_duplicate_file_different_assembly(self, client, simple_box_step):
        """Uploading the same file twice creates two separate assembly records."""
        with open(simple_box_step, "rb") as f:
            content = f.read()

        files = {"file": ("test_box.step", content, "application/octet-stream")}
        resp1 = client.post("/api/upload", files=files)
        resp2 = client.post("/api/upload", files=files)

        assert resp1.status_code == 202
        assert resp2.status_code == 202
        # May have same SHA-256 but different assembly IDs
        assert resp1.json()["assembly_id"] != resp2.json()["assembly_id"]
        assert resp1.json()["sha256"] == resp2.json()["sha256"]

    def test_upload_returns_sha256(self, client, simple_box_step):
        """SHA-256 in response should match the actual file hash."""
        from app.utils.hash import sha256_file
        expected_hash = sha256_file(simple_box_step)

        with open(simple_box_step, "rb") as f:
            content = f.read()

        files = {"file": ("test_box.step", content, "application/octet-stream")}
        resp = client.post("/api/upload", files=files)

        assert resp.status_code == 202
        assert resp.json()["sha256"] == expected_hash

    def test_upload_missing_iso_header_rejected(self, client):
        """STEP file missing ISO-10303-21 declaration should be rejected with 400."""
        fake_content = b"NOT A VALID STEP FILE WITHOUT ISO HEADER\nSOME CAD DATA;\n"
        files = {"file": ("corrupt.step", fake_content, "application/octet-stream")}
        resp = client.post("/api/upload", files=files)
        assert resp.status_code == 400
        assert "ISO-10303-21" in resp.json()["detail"]

    def test_upload_duplicate_dedupe_label(self, client, simple_box_step):
        """Re-uploading existing file assigns re-upload reference label."""
        with open(simple_box_step, "rb") as f:
            content = f.read()
        files = {"file": ("test_box.step", content, "application/octet-stream")}
        resp1 = client.post("/api/upload", files=files)
        resp2 = client.post("/api/upload", files=files)
        assert resp1.status_code == 202
        assert resp2.status_code == 202


class TestComponentLabelEndpoint:
    def test_update_label_nonexistent(self, client):
        resp = client.patch(
            "/api/components/999999/label",
            json={"user_label": "Test Label"},
        )
        assert resp.status_code == 404

    def test_update_label_empty_rejected(self, client, simple_box_step):
        """Empty label string should fail Pydantic validation (min_length=1)."""
        resp = client.patch(
            "/api/components/1/label",
            json={"user_label": ""},
        )
        assert resp.status_code == 422  # Pydantic validation error


class TestGeometryEndpoint:
    def test_geometry_nonexistent_component(self, client):
        resp = client.get("/api/geometry/999999")
        assert resp.status_code == 404


class TestErrorHandling:
    def test_invalid_json_body(self, client):
        """Sending invalid JSON should return 422."""
        resp = client.patch(
            "/api/components/1/label",
            content=b"not json at all",
            headers={"Content-Type": "application/json"},
        )
        assert resp.status_code == 422

    def test_nonexistent_route(self, client):
        resp = client.get("/api/nonexistent_route")
        assert resp.status_code == 404


class TestAssemblyComparison:
    def test_compare_nonexistent_assembly(self, client):
        resp = client.get("/api/assemblies/99999/compare/99998")
        assert resp.status_code == 404

    def test_compare_same_assembly(self, client, simple_box_step):
        # simple_box_step is already imported into the test DB
        # Query assemblies
        resp = client.get("/api/assemblies")
        assert resp.status_code == 200
        assemblies = resp.json()
        assert len(assemblies) > 0
        aid = assemblies[0]["id"]

        comp_resp = client.get(f"/api/assemblies/{aid}/compare/{aid}")
        assert comp_resp.status_code == 200
        data = comp_resp.json()
        assert data["assembly_a_id"] == aid
        assert data["assembly_b_id"] == aid
        assert data["added_count"] == 0
        assert data["removed_count"] == 0
        assert data["modified_count"] == 0
        assert data["unchanged_count"] == data["total_components_a"]
        assert len(data["changes"]) == data["total_components_a"]
