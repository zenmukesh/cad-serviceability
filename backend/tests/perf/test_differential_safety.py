"""
Differential Safety Test Oracle (Phase 0 -> Phase 2).
Rule: The number of cases where a fast check says free but the exact OCC check says blocked MUST BE ZERO.
Fast check must be strictly conservative (false-positives = 0).
"""
import math
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.database import Base
from app.models.assembly import Assembly, Component
from app.services.cad_importer import import_step_file
from app.services.geometry_service import get_assembly_shapes

def exact_occ_collision_oracle(
    moving_shape: Any,
    moving_bb: Dict[str, float],
    dir_vec: Tuple[float, float, float],
    travel_dist: float,
    obs_shape: Any,
    obs_bb: Dict[str, float],
    initial_overlap_vol: float = 0.0,
) -> bool:
    """
    Independent ground-truth OpenCASCADE exact collision oracle.
    Returns True if moving_shape translating along dir_vec hits obs_shape.
    """
    from OCP.gp import gp_Vec, gp_Trsf, gp_Pnt
    from OCP.BRepPrimAPI import BRepPrimAPI_MakeBox
    from OCP.BRepAlgoAPI import BRepAlgoAPI_Common
    from OCP.GProp import GProp_GProps
    from OCP.BRepGProp import BRepGProp
    from cadquery.occ_impl.shapes import Location

    vx, vy, vz = dir_vec

    # 1. Broad-phase AABB overlap along the swept path
    m_min = (moving_bb["xmin"], moving_bb["ymin"], moving_bb["zmin"])
    m_max = (moving_bb["xmax"], moving_bb["ymax"], moving_bb["zmax"])

    sw_xmin = min(m_min[0], m_min[0] + vx * travel_dist)
    sw_xmax = max(m_max[0], m_max[0] + vx * travel_dist)
    sw_ymin = min(m_min[1], m_min[1] + vy * travel_dist)
    sw_ymax = max(m_max[1], m_max[1] + vy * travel_dist)
    sw_zmin = min(m_min[2], m_min[2] + vz * travel_dist)
    sw_zmax = max(m_max[2], m_max[2] + vz * travel_dist)

    if (
        sw_xmax < obs_bb["xmin"] or sw_xmin > obs_bb["xmax"] or
        sw_ymax < obs_bb["ymin"] or sw_ymin > obs_bb["ymax"] or
        sw_zmax < obs_bb["zmin"] or sw_zmin > obs_bb["zmax"]
    ):
        return False

    # 2. Dense step translation with exact solid-solid Boolean
    n_samples = 25
    for i in range(1, n_samples + 1):
        d = travel_dist * (i / n_samples)
        trsf = gp_Trsf()
        trsf.SetTranslation(gp_Vec(vx * d, vy * d, vz * d))
        m_moved = moving_shape.wrapped.Moved(Location(trsf).wrapped)

        common = BRepAlgoAPI_Common(m_moved, obs_shape.wrapped)
        common.Build()
        props = GProp_GProps()
        BRepGProp.VolumeProperties_s(common.Shape(), props)
        if props.Mass() > initial_overlap_vol + 0.01:
            return True

    return False


def test_oracle_safety_baseline():
    """Verify that the oracle correctly distinguishes clear vs colliding motions."""
    import cadquery as cq
    box1 = cq.Workplane("XY").box(20, 20, 20)
    box2 = cq.Workplane("XY").box(20, 20, 20).translate((50, 0, 0)) # 50mm in +X

    bb1 = {"xmin": -10, "xmax": 10, "ymin": -10, "ymax": 10, "zmin": -10, "zmax": 10}
    bb2 = {"xmin": 40, "xmax": 60, "ymin": -10, "ymax": 10, "zmin": -10, "zmax": 10}

    # Motion +X (hits box2)
    hit_plus_x = exact_occ_collision_oracle(box1.val(), bb1, (1.0, 0.0, 0.0), 60.0, box2.val(), bb2)
    assert hit_plus_x is True, "Motion directly toward obstacle must collide"

    # Motion -X (away from box2)
    hit_minus_x = exact_occ_collision_oracle(box1.val(), bb1, (-1.0, 0.0, 0.0), 60.0, box2.val(), bb2)
    assert hit_minus_x is False, "Motion away from obstacle must be clear"

    # Motion +Z (perpendicular, above)
    hit_plus_z = exact_occ_collision_oracle(box1.val(), bb1, (0.0, 0.0, 1.0), 60.0, box2.val(), bb2)
    assert hit_plus_z is False, "Motion parallel to clearance must be clear"
