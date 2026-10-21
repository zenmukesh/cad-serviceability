"""
STEP file importer using OpenCASCADE XCAF assembly-aware reader with fallback to raw STEP topology.

Preserves:
  - Assembly hierarchy (Assemblies and Components)
  - Product names and instance identifiers
  - Global coordinate placements (gp_Trsf transforms)
  - Geometric properties (Volume, Surface Area, Bounding Box)
  - Mesh triangulation for WebGL / Three.js visualization
  - Clean distinction between named assembly components vs inferred solids
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional, List, Dict, Any

from app.services.tessellator import tessellate_cadquery_shape, MeshResult

logger = logging.getLogger(__name__)

_OCP_AVAILABLE = False
_CQ_AVAILABLE = False
_CQ_VERSION = "not-installed"

try:
    import OCP
    from OCP.STEPCAFControl import STEPCAFControl_Reader
    from OCP.TDocStd import TDocStd_Document
    from OCP.XCAFApp import XCAFApp_Application
    from OCP.XCAFDoc import XCAFDoc_DocumentTool
    from OCP.TDataStd import TDataStd_Name
    from OCP.TDF import TDF_LabelSequence, TDF_Label, TDF_Tool
    from OCP.TCollection import TCollection_ExtendedString, TCollection_AsciiString
    from OCP.TopLoc import TopLoc_Location
    from OCP.gp import gp_Trsf
    from OCP.IFSelect import IFSelect_RetDone
    from OCP.STEPControl import STEPControl_Reader
    _OCP_AVAILABLE = True
except ImportError as e:
    logger.warning(f"OCP XCAF classes not available: {e}")

try:
    import cadquery as cq
    from cadquery.occ_impl.shapes import Shape
    _CQ_AVAILABLE = True
    _CQ_VERSION = getattr(cq, "__version__", "installed")
    logger.info(f"CadQuery {_CQ_VERSION} ready for STEP processing")
except ImportError as e:
    logger.warning(f"CadQuery not available: {e}")


@dataclass
class ExtractedMesh:
    """Triangulated surface mesh for browser rendering."""
    vertices: list[float] = field(default_factory=list)
    faces: list[int] = field(default_factory=list)
    normals: list[float] = field(default_factory=list)
    vertex_count: int = 0
    face_count: int = 0


@dataclass
class ExtractedComponent:
    """Extracted component data."""
    cad_entity_id: str
    name: str
    parent_cad_id: str = ""
    depth: int = 0
    is_leaf: bool = True
    component_type: str = "solid"   # 'solid', 'assembly', 'inferred_solid', etc.

    # All in global assembly coordinate frame, mm
    bb_xmin: float = 0.0
    bb_xmax: float = 0.0
    bb_ymin: float = 0.0
    bb_ymax: float = 0.0
    bb_zmin: float = 0.0
    bb_zmax: float = 0.0
    volume_mm3: float = 0.0
    surface_area_mm2: float = 0.0

    # Row-major 4x4 matrix
    placement_matrix: list[float] = field(
        default_factory=lambda: [1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1]
    )

    mesh: Optional[ExtractedMesh] = None


@dataclass
class ImportResult:
    success: bool
    components: list[ExtractedComponent] = field(default_factory=list)
    error: str = ""
    importer_used: str = ""
    warnings: list[str] = field(default_factory=list)


def _get_label_name(lbl: Any) -> str:
    """Extract string name from TDataStd_Name attribute on a TDF_Label."""
    name_attr = TDataStd_Name()
    if lbl.FindAttribute(TDataStd_Name.GetID_s(), name_attr):
        ext_str = name_attr.Get()
        return ext_str.ToExtString()
    return ""


def _get_label_entry(lbl: Any) -> str:
    """Extract entry string tag (e.g. 0:1:1:1) from a TDF_Label."""
    asc = TCollection_AsciiString()
    TDF_Tool.Entry_s(lbl, asc)
    return asc.ToCString()


def _trsf_to_matrix(trsf: gp_Trsf) -> list[float]:
    """Convert an OpenCASCADE gp_Trsf to a 4x4 row-major matrix."""
    return [
        float(trsf.Value(1, 1)), float(trsf.Value(1, 2)), float(trsf.Value(1, 3)), float(trsf.Value(1, 4)),
        float(trsf.Value(2, 1)), float(trsf.Value(2, 2)), float(trsf.Value(2, 3)), float(trsf.Value(2, 4)),
        float(trsf.Value(3, 1)), float(trsf.Value(3, 2)), float(trsf.Value(3, 3)), float(trsf.Value(3, 4)),
        0.0, 0.0, 0.0, 1.0
    ]


def _import_with_xcaf(
    step_path: Path,
    linear_deflection: float,
    angular_deflection: float,
) -> ImportResult:
    """
    Import STEP using OpenCASCADE XCAF framework.
    Preserves assemblies, instances, component names, subassemblies, and placements.
    Avoids duplicate geometry by rendering geometry only on leaf parts.
    """
    result = ImportResult(
        success=False,
        importer_used=f"OpenCASCADE-XCAF (CadQuery {_CQ_VERSION})",
    )

    try:
        app = XCAFApp_Application.GetApplication_s()
        doc = TDocStd_Document(TCollection_ExtendedString("MDTV-XCAF"))
        app.NewDocument(TCollection_ExtendedString("MDTV-XCAF"), doc)

        reader = STEPCAFControl_Reader()
        reader.SetNameMode(True)
        reader.SetPropsMode(True)
        reader.SetColorMode(True)
        reader.SetLayerMode(True)

        status = reader.ReadFile(str(step_path))
        if status != IFSelect_RetDone:
            result.error = f"STEP reader failed to read file with status code: {status}"
            return result

        if not reader.Transfer(doc):
            result.error = "STEP reader failed to transfer document to XCAF"
            return result

        shape_tool = XCAFDoc_DocumentTool.ShapeTool_s(doc.Main())
        free_shapes = TDF_LabelSequence()
        shape_tool.GetFreeShapes(free_shapes)

        if free_shapes.Length() == 0:
            result.warnings.append("No free shapes found in XCAF document; falling back to raw reader")
            return _import_with_raw_step(step_path, linear_deflection, angular_deflection)

        components: list[ExtractedComponent] = []
        entity_counter = 0

        def traverse_node(
            lbl: TDF_Label,
            parent_loc: TopLoc_Location,
            parent_cad_id: str = "",
            depth: int = 0
        ):
            nonlocal entity_counter
            entity_counter += 1

            ref_lbl = TDF_Label()
            has_ref = shape_tool.GetReferredShape_s(lbl, ref_lbl)
            target_lbl = ref_lbl if has_ref else lbl

            inst_name = _get_label_name(lbl)
            ref_name = _get_label_name(target_lbl)

            # Resolve readable component name
            # When an instance name is purely numeric index (e.g. '7', '10') or empty, prefer ref_name
            if ref_name and (not inst_name or inst_name.isdigit()):
                display_name = ref_name
            elif inst_name:
                display_name = inst_name
            else:
                display_name = ref_name or f"Component_{entity_counter}"

            cur_loc = shape_tool.GetLocation_s(lbl)
            combined_loc = parent_loc.Multiplied(cur_loc)
            placement_mat = _trsf_to_matrix(combined_loc.Transformation())

            entry_id = _get_label_entry(lbl) or _get_label_entry(target_lbl) or f"node_{entity_counter:04d}"
            # Unique stable CAD ID including instance path
            cad_id = f"{parent_cad_id}/{entry_id}" if parent_cad_id else entry_id

            is_assembly = shape_tool.IsAssembly_s(target_lbl)

            if is_assembly:
                sub_comps = TDF_LabelSequence()
                shape_tool.GetComponents_s(target_lbl, sub_comps)

                # Assembly container node (does not carry redundant mesh to prevent visual duplicate geometry)
                comp = ExtractedComponent(
                    cad_entity_id=cad_id,
                    name=display_name,
                    parent_cad_id=parent_cad_id,
                    depth=depth,
                    is_leaf=False,
                    component_type="assembly",
                    placement_matrix=placement_mat,
                    mesh=None,
                )
                components.append(comp)

                for k in range(1, sub_comps.Length() + 1):
                    traverse_node(sub_comps.Value(k), combined_loc, cad_id, depth + 1)
            else:
                # Leaf solid or simple shape
                occ_shape = shape_tool.GetShape_s(target_lbl)
                if occ_shape.IsNull():
                    return

                placed_shape = occ_shape.Moved(combined_loc)
                cq_shape = Shape.cast(placed_shape)

                # Compute exact geometric properties
                try:
                    vol = float(cq_shape.Volume())
                except Exception:
                    vol = 0.0

                try:
                    area = float(cq_shape.Area())
                except Exception:
                    area = 0.0

                try:
                    bb = cq_shape.BoundingBox()
                    xmin, xmax = float(bb.xmin), float(bb.xmax)
                    ymin, ymax = float(bb.ymin), float(bb.ymax)
                    zmin, zmax = float(bb.zmin), float(bb.zmax)
                except Exception:
                    xmin = xmax = ymin = ymax = zmin = zmax = 0.0

                # Tessellate for 3D viewer
                mesh_res = tessellate_cadquery_shape(
                    cq_shape,
                    linear_deflection=linear_deflection,
                    angular_deflection=angular_deflection,
                )

                extracted_mesh = None
                if not mesh_res.is_empty:
                    extracted_mesh = ExtractedMesh(
                        vertices=mesh_res.vertices,
                        faces=mesh_res.faces,
                        normals=mesh_res.normals,
                        vertex_count=mesh_res.vertex_count,
                        face_count=mesh_res.face_count,
                    )
                elif mesh_res.warning:
                    result.warnings.append(f"{display_name}: {mesh_res.warning}")

                comp = ExtractedComponent(
                    cad_entity_id=cad_id,
                    name=display_name,
                    parent_cad_id=parent_cad_id,
                    depth=depth,
                    is_leaf=True,
                    component_type="solid",
                    bb_xmin=xmin,
                    bb_xmax=xmax,
                    bb_ymin=ymin,
                    bb_ymax=ymax,
                    bb_zmin=zmin,
                    bb_zmax=zmax,
                    volume_mm3=vol,
                    surface_area_mm2=area,
                    placement_matrix=placement_mat,
                    mesh=extracted_mesh,
                )
                components.append(comp)

        root_loc = TopLoc_Location()
        for i in range(1, free_shapes.Length() + 1):
            root_lbl = free_shapes.Value(i)
            # If the free shape itself is an assembly, traverse its children
            if shape_tool.IsAssembly_s(root_lbl):
                comps = TDF_LabelSequence()
                shape_tool.GetComponents_s(root_lbl, comps)
                for j in range(1, comps.Length() + 1):
                    traverse_node(comps.Value(j), root_loc, "", 0)
            else:
                # Single part root
                traverse_node(root_lbl, root_loc, "", 0)

        # If XCAF traversal resulted in 0 components, fall back to raw reader
        if not components:
            result.warnings.append("XCAF produced no components; falling back to raw STEP topology.")
            return _import_with_raw_step(step_path, linear_deflection, angular_deflection)

        result.success = True
        result.components = components
        return result

    except Exception as e:
        logger.error(f"XCAF import failed with exception: {e}", exc_info=True)
        result.warnings.append(f"XCAF import exception: {e}")
        return _import_with_raw_step(step_path, linear_deflection, angular_deflection)


def _import_with_raw_step(
    step_path: Path,
    linear_deflection: float,
    angular_deflection: float,
) -> ImportResult:
    """
    Fallback importer for non-XCAF STEP files or multi-body parts.
    Decomposes compound topology into individual solids.
    Explicitly labels them as inferred components.
    """
    result = ImportResult(
        success=False,
        importer_used=f"OpenCASCADE-RawTopology (CadQuery {_CQ_VERSION})",
    )

    try:
        reader = STEPControl_Reader()
        status = reader.ReadFile(str(step_path))
        if status != IFSelect_RetDone:
            result.error = f"Raw STEP reader failed with status: {status}"
            return result

        reader.TransferRoots()
        occ_shape = reader.OneShape()

        if occ_shape.IsNull():
            result.error = "Raw STEP reader returned a null shape"
            return result

        cq_shape = Shape.cast(occ_shape)
        solids = cq_shape.Solids()

        comp_type = "inferred_solid" if len(solids) > 1 else "solid"
        if not solids:
            solids = cq_shape.Shells()
            comp_type = "inferred_shell"

        if not solids:
            solids = [cq_shape]
            comp_type = "compound"

        components: list[ExtractedComponent] = []

        for idx, solid in enumerate(solids):
            entity_id = f"solid_{idx:04d}"
            name = f"Inferred_Component_{idx + 1}" if comp_type.startswith("inferred") else f"Component_{idx + 1}"

            try:
                vol = float(solid.Volume())
            except Exception:
                vol = 0.0

            try:
                area = float(solid.Area())
            except Exception:
                area = 0.0

            try:
                bb = solid.BoundingBox()
                xmin, xmax = float(bb.xmin), float(bb.xmax)
                ymin, ymax = float(bb.ymin), float(bb.ymax)
                zmin, zmax = float(bb.zmin), float(bb.zmax)
            except Exception:
                xmin = xmax = ymin = ymax = zmin = zmax = 0.0

            mesh_res = tessellate_cadquery_shape(
                solid,
                linear_deflection=linear_deflection,
                angular_deflection=angular_deflection,
            )

            extracted_mesh = None
            if not mesh_res.is_empty:
                extracted_mesh = ExtractedMesh(
                    vertices=mesh_res.vertices,
                    faces=mesh_res.faces,
                    normals=mesh_res.normals,
                    vertex_count=mesh_res.vertex_count,
                    face_count=mesh_res.face_count,
                )

            comp = ExtractedComponent(
                cad_entity_id=entity_id,
                name=name,
                depth=0,
                is_leaf=True,
                component_type=comp_type,
                bb_xmin=xmin,
                bb_xmax=xmax,
                bb_ymin=ymin,
                bb_ymax=ymax,
                bb_zmin=zmin,
                bb_zmax=zmax,
                volume_mm3=vol,
                surface_area_mm2=area,
                mesh=extracted_mesh,
            )
            components.append(comp)

        result.success = True
        result.components = components
        return result

    except Exception as e:
        logger.error(f"Raw STEP import failed: {e}", exc_info=True)
        result.error = f"Raw STEP reader error: {e}"
        return result


def _import_with_trimesh(step_path: Path) -> ImportResult:
    """Fallback when OpenCASCADE is completely unavailable."""
    import trimesh

    result = ImportResult(success=False, importer_used="trimesh-fallback")
    result.warnings.append("OpenCASCADE not available; using trimesh fallback.")

    try:
        scene = trimesh.load(str(step_path))
    except Exception as e:
        result.error = f"trimesh fallback failed: {e}"
        return result

    if scene is None:
        result.error = "trimesh returned None"
        return result

    if isinstance(scene, trimesh.Scene):
        geom_items = list(scene.geometry.items())
    elif isinstance(scene, trimesh.Trimesh):
        geom_items = [("Component_1", scene)]
    else:
        result.error = f"Unsupported trimesh type: {type(scene)}"
        return result

    components: list[ExtractedComponent] = []
    for idx, (name, tm) in enumerate(geom_items):
        if not isinstance(tm, trimesh.Trimesh) or len(tm.faces) == 0:
            continue
        bb = tm.bounds
        em = ExtractedMesh(
            vertices=tm.vertices.flatten().tolist(),
            faces=tm.faces.flatten().tolist(),
            normals=tm.vertex_normals.flatten().tolist(),
            vertex_count=len(tm.vertices),
            face_count=len(tm.faces),
        )
        components.append(ExtractedComponent(
            cad_entity_id=f"trimesh_{idx:04d}",
            name=name or f"Component_{idx + 1}",
            is_leaf=True,
            component_type="inferred_solid",
            bb_xmin=float(bb[0][0]), bb_xmax=float(bb[1][0]),
            bb_ymin=float(bb[0][1]), bb_ymax=float(bb[1][1]),
            bb_zmin=float(bb[0][2]), bb_zmax=float(bb[1][2]),
            volume_mm3=float(tm.volume) if tm.is_watertight else 0.0,
            surface_area_mm2=float(tm.area),
            mesh=em,
        ))

    if not components:
        result.error = "No valid geometry found by trimesh"
        return result

    result.success = True
    result.components = components
    return result


def import_step_file(
    step_path: Path,
    linear_deflection: float = 0.5,
    angular_deflection: float = 0.1,
) -> ImportResult:
    """
    Main entry point for STEP assembly import.
    Uses assembly-aware XCAF reader first, then raw topology decomposition.
    """
    if not step_path.exists():
        return ImportResult(success=False, error=f"File not found: {step_path}")

    suffix = step_path.suffix.lower()
    if suffix not in {".step", ".stp"}:
        return ImportResult(
            success=False,
            error=f"Unsupported file extension '{suffix}'. Only .step and .stp are accepted.",
        )

    if _OCP_AVAILABLE and _CQ_AVAILABLE:
        return _import_with_xcaf(step_path, linear_deflection, angular_deflection)
    else:
        return _import_with_trimesh(step_path)
