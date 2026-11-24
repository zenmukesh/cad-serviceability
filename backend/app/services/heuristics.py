"""
Mechanical Engineering Serviceability Heuristics & Geometric Fallbacks.
Centralizes all pattern keywords and provides fallback detection for unnamed CAD solids.
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional

# Standard mechanical nomenclature keywords (case-insensitive substring matches)
BASE_PLATE_KEYWORDS: List[str] = [
    "baseplate",
    "bedplate",
    "foundation",
]

FASTENER_KEYWORDS: List[str] = [
    "bolt",
    "screw",
    "fastener",
    "nut",
    "washer",
    "shank",
    "stud",
]

SHAFT_OR_ROTATING_KEYWORDS: List[str] = [
    "shaft",
    "spindle",
    "axle",
    "rotor",
    "gear",
    "pinion",
    "sprocket",
]

COVER_OR_HOUSING_KEYWORDS: List[str] = [
    "cover",
    "cap",
    "casing",
    "housing",
    "shield",
    "enclosure",
    "lid",
    "guard",
]

PRIORITY_Z_REMOVAL_KEYWORDS: List[str] = [
    "screw",
    "bolt",
    "dipstick",
    "gear",
    "pinion",
    "sprocket",
]


def is_fastener(name: str, comp: Any = None) -> bool:
    """
    Detect if a component is a fastener using name matching first,
    falling back to geometric bounding dimensions if the CAD name is generic.
    """
    q = name.lower() if name else ""
    if any(k in q for k in FASTENER_KEYWORDS):
        return True

    # Cheap geometric fallback: small volume & elongated aspect ratio
    if comp is not None:
        return is_geometric_fastener(comp)
    return False


def is_geometric_fastener(comp: Any) -> bool:
    """Checks if component dimensions resemble standard hardware pins/bolts."""
    try:
        dx = abs(getattr(comp, "bb_xmax", 0) - getattr(comp, "bb_xmin", 0))
        dy = abs(getattr(comp, "bb_ymax", 0) - getattr(comp, "bb_ymin", 0))
        dz = abs(getattr(comp, "bb_zmax", 0) - getattr(comp, "bb_zmin", 0))
        dims = sorted([dx, dy, dz])
        min_dim, mid_dim, max_dim = dims[0], dims[1], dims[2]

        # Small cross-section and elongated along one axis
        vol = getattr(comp, "volume_mm3", 0)
        if 0 < vol < 8000.0 and max_dim > 2.0 * max(min_dim, mid_dim, 0.1):
            return True
    except Exception:
        pass
    return False


def is_baseplate(name: str, comp: Any = None, all_components: Optional[List[Any]] = None) -> bool:
    """
    Detect if a component is a foundation / baseplate by name,
    falling back to lowest elevation and largest footprint area.
    """
    q = name.lower() if name else ""
    if any(k in q for k in BASE_PLATE_KEYWORDS):
        return True

    # Cheap geometric fallback if name is generic or unnamed CAD solid
    if comp is not None and all_components and (not name or name.lower().startswith("solid") or name.lower().startswith("part")):
        return is_geometric_baseplate(comp, all_components)
    return False


def is_geometric_baseplate(comp: Any, all_components: List[Any]) -> bool:
    """Detect foundation solid by lowest Z position and largest horizontal area."""
    try:
        min_z = min(getattr(c, "bb_zmin", 0) for c in all_components)
        if abs(getattr(comp, "bb_zmin", 0) - min_z) <= 1.0:
            footprints = [
                abs(getattr(c, "bb_xmax", 0) - getattr(c, "bb_xmin", 0)) *
                abs(getattr(c, "bb_ymax", 0) - getattr(c, "bb_ymin", 0))
                for c in all_components
            ]
            max_footprint = max(footprints) if footprints else 0
            comp_footprint = (
                abs(getattr(comp, "bb_xmax", 0) - getattr(comp, "bb_xmin", 0)) *
                abs(getattr(comp, "bb_ymax", 0) - getattr(comp, "bb_ymin", 0))
            )
            if max_footprint > 0 and comp_footprint >= 0.7 * max_footprint:
                return True
    except Exception:
        pass
    return False


def is_housing_or_cover(name: str) -> bool:
    """Detect if a component is a protective housing, cover, guard, or shield."""
    q = name.lower() if name else ""
    return any(k in q for k in COVER_OR_HOUSING_KEYWORDS)
