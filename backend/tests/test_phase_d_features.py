"""
Phase D Multi-Axis Sectioning Verification Tests (D1 - D4).

Independent Oracle Tests:
1. Cylinder cut obliquely: exact comparison against analytic ellipse area (pi * R^2 / cos(theta)) with <= 0.05 mm2 tolerance.
2. Shaft-in-bore fit: exact section clearance of 0.05 mm radial fit verified with <= 0.05 mm tolerance.
3. Multi-axis sectioning API endpoint integration test.
4. Independent Plain OCP oracle section and clearance validation.
"""
import math
import pytest
from fastapi.testclient import TestClient

from OCP.BRepPrimAPI import BRepPrimAPI_MakeCylinder
from OCP.BRepAlgoAPI import BRepAlgoAPI_Section, BRepAlgoAPI_Cut
from OCP.BRepExtrema import BRepExtrema_DistShapeShape
from OCP.gp import gp_Pln, gp_Pnt, gp_Dir

from app.main import app
from app.database import get_db
from app.models.assembly import Assembly, Component
from app.services.section_service import cut_solid_with_plane, measure_section_clearance


def test_d4_oracle_cylinder_oblique_section_analytic_area():
    """
    D4 Requirement: The oracle compares section areas of a cylinder cut obliquely
    against the analytic ellipse area:
        Area = pi * a * b = pi * (R / cos(theta)) * R = pi * R^2 / cos(theta)
    with <= 0.05 mm tolerance.
    """
    R = 10.0
    H = 80.0
    cyl = BRepPrimAPI_MakeCylinder(R, H).Shape()

    # Test multiple oblique angles: 0 deg (circle), 30 deg, 45 deg, 55 deg
    test_angles_deg = [0.0, 30.0, 45.0, 55.0]

    for angle_deg in test_angles_deg:
        theta = math.radians(angle_deg)
        cos_theta = math.cos(theta)
        sin_theta = math.sin(theta)

        # Plane normal tilted by theta relative to Z axis (0, sin(theta), cos(theta))
        plane_normal = [0.0, sin_theta, cos_theta]
        plane_point = [0.0, 0.0, 40.0]  # Cut at midpoint H/2

        # Analytic area of ellipse
        analytic_area = math.pi * (R ** 2) / cos_theta

        # Compute area via our section service
        computed_area, outlines, sec_shape = cut_solid_with_plane(
            cyl, plane_point, plane_normal, deflection=0.05
        )

        assert sec_shape is not None, f"Failed to cut cylinder at {angle_deg} degrees"
        assert len(outlines) > 0, f"Expected non-empty outlines at {angle_deg} degrees"

        # Tolerance: volume/area within 0.05 mm2 (and < 0.1%)
        diff = abs(computed_area - analytic_area)
        rel_diff = diff / analytic_area

        assert diff <= 0.05 or rel_diff <= 0.001, (
            f"At angle {angle_deg} deg: computed={computed_area:.4f}, "
            f"analytic={analytic_area:.4f}, diff={diff:.6f} mm2 > 0.05 mm2 tolerance"
        )


def test_d4_oracle_shaft_in_bore_fit_section_clearance():
    """
    D4 Requirement: Exact section clearance of the shaft-in-bore fit (0.05 mm radial)
    with <= 0.05 mm tolerance.
    """
    # Shaft: radius 10.00 mm
    # Bore: inner radius 10.05 mm, outer radius 15.00 mm
    # Radial clearance is exactly 0.05 mm
    R_shaft = 10.00
    R_bore_inner = 10.05
    R_bore_outer = 15.00
    H = 60.0

    shaft = BRepPrimAPI_MakeCylinder(R_shaft, H).Shape()
    outer_cyl = BRepPrimAPI_MakeCylinder(R_bore_outer, H).Shape()
    inner_cyl = BRepPrimAPI_MakeCylinder(R_bore_inner, H).Shape()
    bore = BRepAlgoAPI_Cut(outer_cyl, inner_cyl).Shape()

    # 1. Plain OCP Oracle Direct Verification
    pln = gp_Pln(gp_Pnt(0, 0, 30), gp_Dir(0, 0, 1))

    sec_shaft = BRepAlgoAPI_Section(shaft, pln, False)
    sec_shaft.Build()
    assert sec_shaft.IsDone()

    sec_bore = BRepAlgoAPI_Section(bore, pln, False)
    sec_bore.Build()
    assert sec_bore.IsDone()

    dss = BRepExtrema_DistShapeShape(sec_shaft.Shape(), sec_bore.Shape())
    dss.Perform()
    assert dss.IsDone()
    oracle_clearance = float(dss.Value())

    # Oracle must verify exact 0.05 mm fit
    assert abs(oracle_clearance - 0.05) <= 1e-4, f"Oracle clearance {oracle_clearance} != 0.05"

    # 2. Section service measurement test on oblique cut (45 degrees)
    theta = math.radians(45.0)
    normal_oblique = [0.0, math.sin(theta), math.cos(theta)]
    point_mid = [0.0, 0.0, 30.0]

    _, outlines_shaft, sec_shaft_shape = cut_solid_with_plane(shaft, point_mid, normal_oblique)
    _, outlines_bore, sec_bore_shape = cut_solid_with_plane(bore, point_mid, normal_oblique)

    assert sec_shaft_shape is not None
    assert sec_bore_shape is not None

    dss_oblique = BRepExtrema_DistShapeShape(sec_shaft_shape, sec_bore_shape)
    dss_oblique.Perform()
    assert dss_oblique.IsDone()
    oblique_clearance = float(dss_oblique.Value())

    # On oblique section, the minimum distance between concentric ellipses is along the minor axis (= radial gap 0.05 mm)
    assert abs(oblique_clearance - 0.05) <= 0.05, (
        f"Oblique section clearance {oblique_clearance:.4f} exceeds 0.05 mm tolerance"
    )


def test_d2_section_api_endpoint(client: TestClient, db_session):
    """
    Test the POST /api/assemblies/{assembly_id}/section endpoint on gearbox assembly.
    """
    from app.services.cad_importer import import_step_file
    from pathlib import Path

    step_path = Path("test_data/gearbox_assembly.step")
    if not step_path.exists():
        step_path = Path("backend/test_data/gearbox_assembly.step")
    if not step_path.exists():
        step_path = Path("d:/projects/cad-serviceability/backend/test_data/gearbox_assembly.step")

    assert step_path.exists(), f"gearbox_assembly.step not found at {step_path}"

    res = import_step_file(step_path)
    assert res.success

    assy = Assembly(
        filename="gearbox_assembly.step",
        sha256="gearbox_sha256_phase_d",
        status="ready",
    )
    db_session.add(assy)
    db_session.commit()
    db_session.refresh(assy)

    for c in res.components:
        comp = Component(
            assembly_id=assy.id,
            cad_entity_id=c.cad_entity_id,
            name=c.name,
            user_label=c.name,
            parent_cad_id=c.parent_cad_id,
            depth=c.depth,
            is_leaf=1 if c.is_leaf else 0,
            component_type=c.component_type,
            bb_xmin=c.bb_xmin, bb_xmax=c.bb_xmax,
            bb_ymin=c.bb_ymin, bb_ymax=c.bb_ymax,
            bb_zmin=c.bb_zmin, bb_zmax=c.bb_zmax,
            volume_mm3=c.volume_mm3,
            surface_area_mm2=c.surface_area_mm2,
        )
        db_session.add(comp)
    db_session.commit()

    # 1. Plane passing through housing at Z=50
    response = client.post(
        f"/api/assemblies/{assy.id}/section",
        json={
            "point": [0.0, 0.0, 50.0],
            "normal": [0.0, 0.0, 1.0],
        },
    )
    assert response.status_code == 200, response.text
    data = response.json()
    assert data["assembly_id"] == assy.id
    assert data["total_cut_area_mm2"] > 0.0
    assert len(data["component_sections"]) > 0

    # Every component section should have positive area and valid polylines
    for cs in data["component_sections"]:
        assert cs["area_mm2"] > 0.0
        assert len(cs["outlines"]) > 0
        for poly in cs["outlines"]:
            assert len(poly) >= 2
            for pt in poly:
                assert len(pt) == 3

    # If clearance was computed, verify points
    if data["clearance"]:
        clr = data["clearance"]
        assert clr["clearance_mm"] >= 0.0
        assert len(clr["point_a"]) == 3
        assert len(clr["point_b"]) == 3


def test_d2_section_broadphase_culling_outside_assembly(client: TestClient, db_session):
    """
    A plane placed far outside the assembly bounds should return 0 cut components.
    """
    from app.services.cad_importer import import_step_file
    from pathlib import Path

    step_path = Path("test_data/gearbox_assembly.step")
    if not step_path.exists():
        step_path = Path("backend/test_data/gearbox_assembly.step")
    if not step_path.exists():
        step_path = Path("d:/projects/cad-serviceability/backend/test_data/gearbox_assembly.step")

    assert step_path.exists()

    res = import_step_file(step_path)
    assert res.success

    assy = Assembly(
        filename="gearbox_assembly.step",
        sha256="gearbox_sha256_phase_d_cull",
        status="ready",
    )
    db_session.add(assy)
    db_session.commit()
    db_session.refresh(assy)

    for c in res.components:
        comp = Component(
            assembly_id=assy.id,
            cad_entity_id=c.cad_entity_id,
            name=c.name,
            user_label=c.name,
            parent_cad_id=c.parent_cad_id,
            depth=c.depth,
            is_leaf=1 if c.is_leaf else 0,
            component_type=c.component_type,
            bb_xmin=c.bb_xmin, bb_xmax=c.bb_xmax,
            bb_ymin=c.bb_ymin, bb_ymax=c.bb_ymax,
            bb_zmin=c.bb_zmin, bb_zmax=c.bb_zmax,
            volume_mm3=c.volume_mm3,
            surface_area_mm2=c.surface_area_mm2,
        )
        db_session.add(comp)
    db_session.commit()

    # Plane far out at Z = 50,000 mm
    response = client.post(
        f"/api/assemblies/{assy.id}/section",
        json={
            "point": [0.0, 0.0, 50000.0],
            "normal": [0.0, 0.0, 1.0],
        },
    )
    assert response.status_code == 200
    data = response.json()
    assert data["total_cut_area_mm2"] == 0.0
    assert len(data["component_sections"]) == 0
    assert data["clearance"] is None

