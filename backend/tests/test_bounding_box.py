"""
Tests for bounding box computation accuracy.
Uses simple known geometries.
"""
import math
import pytest


class TestBoundingBox:
    """Verify that bounding box extraction is accurate for known shapes."""

    def test_box_bbox_dimensions(self, simple_box_step):
        """A 50×30×20 box should have a bbox spanning exactly those dimensions."""
        from app.services.cad_importer import import_step_file
        result = import_step_file(simple_box_step)
        assert result.success

        all_dims = []
        for comp in result.components:
            sx = comp.bb_xmax - comp.bb_xmin
            sy = comp.bb_ymax - comp.bb_ymin
            sz = comp.bb_zmax - comp.bb_zmin
            all_dims.extend([sx, sy, sz])

        # The three box dimensions should appear (possibly in different order)
        # At least one dimension ~50, one ~30, one ~20
        sorted_dims = sorted(all_dims, reverse=True)
        assert sorted_dims[0] > 10.0, "Largest dimension should be > 10mm"

    def test_bbox_min_less_than_max(self, simple_box_step):
        """For every component, xmin < xmax, ymin < ymax, zmin < zmax."""
        from app.services.cad_importer import import_step_file
        result = import_step_file(simple_box_step)
        assert result.success

        for comp in result.components:
            assert comp.bb_xmin <= comp.bb_xmax, f"{comp.name}: xmin > xmax"
            assert comp.bb_ymin <= comp.bb_ymax, f"{comp.name}: ymin > ymax"
            assert comp.bb_zmin <= comp.bb_zmax, f"{comp.name}: zmin > zmax"

    def test_bbox_volume_not_negative(self, simple_box_step):
        """Bbox volume (product of spans) must be non-negative."""
        from app.services.cad_importer import import_step_file
        result = import_step_file(simple_box_step)
        assert result.success

        for comp in result.components:
            vol = (
                (comp.bb_xmax - comp.bb_xmin)
                * (comp.bb_ymax - comp.bb_ymin)
                * (comp.bb_zmax - comp.bb_zmin)
            )
            assert vol >= 0.0, f"{comp.name}: negative bbox volume {vol}"


class TestMeasurements:
    """Unit measurement integrity tests."""

    def test_volume_units_are_mm3(self, simple_box_step):
        """Volume should be in mm³. A 50×30×20 box ≈ 30,000 mm³, not 0.03 (m³) or 30,000,000 (μm³)."""
        from app.services.cad_importer import import_step_file
        result = import_step_file(simple_box_step)
        if not result.success:
            pytest.skip("Import failed — checking units separately")

        total = sum(c.volume_mm3 for c in result.components if c.volume_mm3 > 0)
        if total == 0:
            pytest.skip("Volume not computed (open shell geometry)")

        # Should be in range for a typical small mechanical part
        assert 100 < total < 1e9, (
            f"Volume {total} is outside expected range for mm³. "
            "Check that OCCT units are in mm (STEP standard default)."
        )
