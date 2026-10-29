"""
Upload router — handles STEP file ingestion.

POST /api/upload
  - Validates file extension and size
  - Saves to disk
  - Computes SHA-256
  - Creates Assembly record with status=processing
  - Runs STEP import in a background thread (not blocking the event loop)
  - Updates DB record with extracted components
"""
from __future__ import annotations

import json
import logging
import os
import shutil
import tempfile
from pathlib import Path

from fastapi import APIRouter, BackgroundTasks, Depends, File, HTTPException, UploadFile, status
from sqlalchemy.orm import Session

from app.config import settings
from app.database import get_db, SessionLocal
from app.models.assembly import Assembly, Component
from app.schemas.assembly import UploadResponse, ErrorResponse
from app.services.cad_importer import import_step_file
from app.utils.hash import sha256_file
from app.utils.version_info import collect_versions

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api", tags=["upload"])

ALLOWED_EXTENSIONS = {".step", ".stp"}
MAX_BYTES = settings.max_upload_size_mb * 1024 * 1024


def _process_step_async(assembly_id: int, file_path: Path, db_url: str):
    """
    Run STEP import in a background thread (called by BackgroundTasks).
    Creates its own DB session because FastAPI's session is request-scoped.
    """
    db = SessionLocal()

    try:
        assembly: Assembly = db.query(Assembly).filter(Assembly.id == assembly_id).first()
        if not assembly:
            logger.error(f"Assembly {assembly_id} not found in background task")
            return

        result = import_step_file(
            file_path,
            linear_deflection=settings.tessellation_linear_deflection,
            angular_deflection=settings.tessellation_angular_deflection,
        )

        if not result.success:
            assembly.status = "error"
            assembly.error_message = result.error
            db.commit()
            logger.error(f"Import failed for assembly {assembly_id}: {result.error}")
            return

        # Persist components
        for comp_data in result.components:
            mesh_json = ""
            if comp_data.mesh and comp_data.mesh.vertex_count > 0:
                mesh_json = json.dumps({
                    "vertices": comp_data.mesh.vertices,
                    "faces": comp_data.mesh.faces,
                    "normals": comp_data.mesh.normals,
                    "vertex_count": comp_data.mesh.vertex_count,
                    "face_count": comp_data.mesh.face_count,
                })

            component = Component(
                assembly_id=assembly_id,
                cad_entity_id=comp_data.cad_entity_id,
                name=comp_data.name,
                user_label="",
                parent_cad_id=comp_data.parent_cad_id,
                depth=comp_data.depth,
                is_leaf=1 if comp_data.is_leaf else 0,
                component_type=comp_data.component_type,
                bb_xmin=comp_data.bb_xmin,
                bb_xmax=comp_data.bb_xmax,
                bb_ymin=comp_data.bb_ymin,
                bb_ymax=comp_data.bb_ymax,
                bb_zmin=comp_data.bb_zmin,
                bb_zmax=comp_data.bb_zmax,
                volume_mm3=comp_data.volume_mm3,
                surface_area_mm2=comp_data.surface_area_mm2,
                placement_matrix=json.dumps(comp_data.placement_matrix),
                mesh_json=mesh_json,
            )
            db.add(component)

        # Add warnings to error_message if any
        if result.warnings:
            assembly.error_message = "; ".join(result.warnings)

        assembly.status = "ready"
        assembly.importer_version = result.importer_used
        db.commit()
        logger.info(
            f"Assembly {assembly_id}: import complete - "
            f"{len(result.components)} component(s)"
        )

    except Exception as e:
        logger.error(f"Background import crashed for assembly {assembly_id}: {e}", exc_info=True)
        try:
            assembly = db.query(Assembly).filter(Assembly.id == assembly_id).first()
            if assembly:
                assembly.status = "error"
                assembly.error_message = f"Internal processing error: {e}"
                db.commit()
        except Exception:
            pass
    finally:
        db.close()


@router.post(
    "/upload",
    response_model=UploadResponse,
    status_code=status.HTTP_202_ACCEPTED,
    summary="Upload a STEP assembly file",
    responses={
        400: {"model": ErrorResponse, "description": "Invalid file type or corrupted STEP"},
        413: {"model": ErrorResponse, "description": "File exceeds size limit"},
    },
)
async def upload_step_file(
    background_tasks: BackgroundTasks,
    file: UploadFile = File(..., description="STEP file (.step or .stp)"),
    revision_label: str = "",
    db: Session = Depends(get_db),
):
    """
    Upload a STEP assembly file for processing.

    The file is saved and queued for background import. The response is
    returned immediately with status='processing'. Poll
    GET /api/assemblies/{id} to check when status changes to 'ready' or 'error'.
    """
    # Validate extension
    suffix = Path(file.filename).suffix.lower() if file.filename else ""
    if suffix not in ALLOWED_EXTENSIONS:
        raise HTTPException(
            status_code=400,
            detail=f"Unsupported file type '{suffix}'. Accepted: .step, .stp",
        )

    # Read file content with size guard
    content = await file.read(MAX_BYTES + 1)
    if len(content) > MAX_BYTES:
        raise HTTPException(
            status_code=413,
            detail=f"File exceeds maximum size of {settings.max_upload_size_mb} MB",
        )
    if len(content) == 0:
        raise HTTPException(status_code=400, detail="Uploaded file is empty")

    # Save to uploads directory
    upload_dir = Path(settings.upload_dir)
    upload_dir.mkdir(parents=True, exist_ok=True)

    # Temporary file first, then move (atomic)
    tmp_fd, tmp_path = tempfile.mkstemp(suffix=suffix, dir=upload_dir)
    try:
        with os.fdopen(tmp_fd, "wb") as f:
            f.write(content)

        file_hash = sha256_file(Path(tmp_path))
        final_path = upload_dir / f"{file_hash}{suffix}"
        shutil.move(tmp_path, str(final_path))
    except Exception as e:
        try:
            os.unlink(tmp_path)
        except Exception:
            pass
        raise HTTPException(status_code=500, detail=f"Failed to save file: {e}")

    # Create Assembly record
    versions = collect_versions()
    assembly = Assembly(
        filename=file.filename,
        sha256=file_hash,
        revision_label=revision_label,
        status="processing",
        software_versions=json.dumps(versions),
    )
    db.add(assembly)
    db.commit()
    db.refresh(assembly)

    # Queue background processing
    background_tasks.add_task(
        _process_step_async,
        assembly.id,
        final_path,
        settings.database_url,
    )

    logger.info(
        f"Accepted upload: {file.filename} ({len(content)} bytes) "
        f"-> assembly_id={assembly.id}"
    )

    return UploadResponse(
        assembly_id=assembly.id,
        filename=file.filename,
        sha256=file_hash,
        status="processing",
        message=(
            "File accepted. Processing started in background. "
            f"Poll GET /api/assemblies/{assembly.id} for status."
        ),
    )
