"""ORM models for Assembly and Component entities."""
import json
from datetime import datetime, timezone

from sqlalchemy import (
    Column, DateTime, Float, ForeignKey, Integer, String, Text, event
)
from sqlalchemy.orm import relationship

from app.database import Base


class Assembly(Base):
    """Represents one imported STEP file / assembly revision."""
    __tablename__ = "assemblies"

    id = Column(Integer, primary_key=True, index=True)
    filename = Column(String(512), nullable=False)
    sha256 = Column(String(64), nullable=False, index=True)
    revision_label = Column(String(128), default="")
    imported_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))
    status = Column(String(32), default="pending")  # pending|processing|ready|error
    error_message = Column(Text, default="")

    # Traceability
    importer_version = Column(String(64), default="")
    software_versions = Column(Text, default="{}")  # JSON string

    # Relationships
    components = relationship("Component", back_populates="assembly", cascade="all, delete-orphan")

    def get_software_versions(self) -> dict:
        try:
            return json.loads(self.software_versions or "{}")
        except Exception:
            return {}


class Component(Base):
    """One component (solid body / instance) extracted from a STEP assembly."""
    __tablename__ = "components"

    id = Column(Integer, primary_key=True, index=True)
    assembly_id = Column(Integer, ForeignKey("assemblies.id"), nullable=False, index=True)

    # CAD identity — preserved from the OCCT/STEP entity
    cad_entity_id = Column(String(256), default="")   # OCCT label or STEP entity ref
    name = Column(String(512), default="")             # Name from STEP / OCCT
    user_label = Column(String(512), default="")       # User-editable override

    # Hierarchy
    parent_cad_id = Column(String(256), default="")    # Parent entity id (blank = root)
    depth = Column(Integer, default=0)

    # Bounding box (axis-aligned, in mm, in assembly coordinate frame)
    bb_xmin = Column(Float, default=0.0)
    bb_xmax = Column(Float, default=0.0)
    bb_ymin = Column(Float, default=0.0)
    bb_ymax = Column(Float, default=0.0)
    bb_zmin = Column(Float, default=0.0)
    bb_zmax = Column(Float, default=0.0)

    # Geometric properties (computed from BREP)
    volume_mm3 = Column(Float, default=0.0)
    surface_area_mm2 = Column(Float, default=0.0)

    # 4x4 placement matrix (row-major, JSON string)
    placement_matrix = Column(Text, default="")

    # Tessellated mesh for the viewer (JSON: {vertices, faces, normals})
    # Stored as compressed JSON; large assemblies should offload this to a file.
    mesh_json = Column(Text, default="")

    # Metadata
    is_leaf = Column(Integer, default=1)  # 1 if no sub-components (SQLite bool)
    component_type = Column(String(64), default="solid")  # solid|compound|shell|wire

    assembly = relationship("Assembly", back_populates="components")

    @property
    def display_name(self) -> str:
        return self.user_label or self.name or f"Component_{self.id}"

    @property
    def bounding_box(self) -> dict:
        return {
            "xmin": self.bb_xmin, "xmax": self.bb_xmax,
            "ymin": self.bb_ymin, "ymax": self.bb_ymax,
            "zmin": self.bb_zmin, "zmax": self.bb_zmax,
            "size_x": self.bb_xmax - self.bb_xmin,
            "size_y": self.bb_ymax - self.bb_ymin,
            "size_z": self.bb_zmax - self.bb_zmin,
        }
