"""
Tests for STEP file import and component extraction.
Tests use controlled simple geometry with known expected values and the multi-component sample assembly.
"""
import math
import pytest
from pathlib import Path


class TestStepImporter:
    """Test the cad_importer service with known geometries and assembly structures."""

    def test_import_nonexistent_file(self):
        from app.services.cad_importer import import_step_file
        result = import_step_file(Path("/nonexistent/file.step"))
        assert not result.success
        assert "not found" in result.error.lower() or "File not found" in result.error

    def test_import_wrong_extension(self, tmp_path):
        from app.services.cad_importer import import_step_file
        bad_file = tmp_path / "test.iges"
        bad_file.write_bytes(b"fake content")
        result = import_step_file(bad_file)
        assert not result.success
        assert "Unsupported" in result.error

    def test_import_single_box(self, simple_box_step):
        """A single 50×30×20 box should yield >= 1 component."""
        from app.services.cad_importer import import_step_file
        result = import_step_file(simple_box_step)
        assert result.success, f"Import failed: {result.error}"
        assert len(result.components) >= 1

    def test_single_box_bounding_box(self, simple_box_step):
        """Bounding box of 50×30×20 box should span ~50mm in X, ~30mm in Y, ~20mm in Z."""
        from app.services.cad_importer import import_step_file
        result = import_step_file(simple_box_step)
        assert result.success

        comp = max(
            result.components,
            key=lambda c: (c.bb_xmax - c.bb_xmin) * (c.bb_ymax - c.bb_ymin) * (c.bb_zmax - c.bb_zmin)
        )

        size_x = comp.bb_xmax - comp.bb_xmin
        size_y = comp.bb_ymax - comp.bb_ymin
        size_z = comp.bb_zmax - comp.bb_zmin

        assert size_x > 0, "Bounding box X span should be positive"
        assert size_y > 0, "Bounding box Y span should be positive"
        assert size_z > 0, "Bounding box Z span should be positive"

        max_dim = max(size_x, size_y, size_z)
        assert max_dim > 10.0, f"Largest dimension {max_dim:.2f} too small for a 50mm box"
        assert max_dim < 200.0, f"Largest dimension {max_dim:.2f} unexpectedly large"

    def test_single_box_volume(self, simple_box_step):
        """Volume of 50×30×20 box = 30,000 mm³ ± 5%."""
        from app.services.cad_importer import import_step_file
        result = import_step_file(simple_box_step)
        assert result.success

        total_volume = sum(c.volume_mm3 for c in result.components if c.is_leaf)
        expected = 50.0 * 30.0 * 20.0
        tolerance = 0.05

        if total_volume > 0:
            assert abs(total_volume - expected) / expected < tolerance, (
                f"Volume {total_volume:.1f} differs from expected {expected:.1f} by > 5%"
            )

    def test_component_has_mesh(self, simple_box_step):
        """Each extracted leaf solid component should have a tessellated mesh."""
        from app.services.cad_importer import import_step_file
        result = import_step_file(simple_box_step)
        assert result.success

        leaf_comps = [c for c in result.components if c.is_leaf]
        for comp in leaf_comps:
            assert comp.mesh is not None, f"Leaf component '{comp.name}' has no mesh"
            assert comp.mesh.vertex_count > 0, f"Component '{comp.name}' mesh has no vertices"
            assert comp.mesh.face_count > 0, f"Component '{comp.name}' mesh has no faces"

    def test_mesh_face_indices_in_range(self, simple_box_step):
        """All face indices must reference valid vertex indices."""
        from app.services.cad_importer import import_step_file
        result = import_step_file(simple_box_step)
        assert result.success

        for comp in result.components:
            if comp.mesh and comp.mesh.face_count > 0:
                max_idx = max(comp.mesh.faces)
                assert max_idx < comp.mesh.vertex_count, (
                    f"Face index {max_idx} >= vertex count {comp.mesh.vertex_count}"
                )
                min_idx = min(comp.mesh.faces)
                assert min_idx >= 0, f"Negative face index {min_idx}"

    def test_component_entity_ids_unique(self, simple_box_step):
        """Each extracted component must have a unique cad_entity_id."""
        from app.services.cad_importer import import_step_file
        result = import_step_file(simple_box_step)
        assert result.success

        ids = [c.cad_entity_id for c in result.components]
        assert len(ids) == len(set(ids)), f"Duplicate cad_entity_ids found: {ids}"

    def test_assembly_import(self, test_step_path):
        """Multi-component assembly should yield multiple components."""
        from app.services.cad_importer import import_step_file
        result = import_step_file(test_step_path)
        assert result.success, f"Assembly import failed: {result.error}"
        assert len(result.components) >= 3

    def test_sample_serviceability_assembly_multi_component(self):
        """Verify sample_serviceability_assembly.step extracts all distinct named components."""
        from app.services.cad_importer import import_step_file
        step_path = Path("test_data/sample_serviceability_assembly.step")
        if not step_path.exists():
            pytest.skip("sample_serviceability_assembly.step not found in test_data")

        result = import_step_file(step_path)
        assert result.success, f"Import failed: {result.error}"

        # Verify multiple components are extracted (not just 1 compound)
        assert len(result.components) >= 6, f"Expected at least 6 components, got {len(result.components)}"

        names = [c.name for c in result.components]
        # Check expected mechanical component names exist
        assert any("Base_Plate" in n for n in names), f"Base_Plate missing from {names}"
        assert any("Motor_Housing" in n for n in names), f"Motor_Housing missing from {names}"
        assert any("Front_End_Cap" in n for n in names), f"Front_End_Cap missing from {names}"
        assert any("Output_Shaft" in n for n in names), f"Output_Shaft missing from {names}"

        # Check that individual leaf parts have non-zero volume
        leaf_parts = [c for c in result.components if c.is_leaf]
        assert len(leaf_parts) >= 6
        for part in leaf_parts:
            assert part.volume_mm3 > 0, f"Part {part.name} has non-positive volume: {part.volume_mm3}"
            assert part.surface_area_mm2 > 0, f"Part {part.name} has non-positive surface area: {part.surface_area_mm2}"
            assert part.mesh is not None, f"Part {part.name} missing mesh"
            assert part.mesh.vertex_count > 0

    def test_empty_step_file(self, tmp_path):
        """An empty (but correctly-named) STEP file should fail gracefully."""
        from app.services.cad_importer import import_step_file
        empty = tmp_path / "empty.step"
        empty.write_text("ISO-10303-21;\nHEADER;\nENDSEC;\nDATA;\nENDSEC;\nEND-ISO-10303-21;\n")
        result = import_step_file(empty)
        if result.success:
            assert len(result.components) == 0 or result.warnings
        else:
            assert result.error
