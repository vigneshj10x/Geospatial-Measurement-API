"""REST API endpoints for geospatial file upload, status lifecycle, metadata, and measurements."""

import shutil
import uuid
from collections import Counter
from pathlib import Path
from typing import Any

from fastapi import (
    APIRouter,
    BackgroundTasks,
    Depends,
    File,
    Query,
    Response,
    UploadFile,
    status,
)
from sqlalchemy.orm import Session

from app.config import settings
from app.db import SessionLocal, get_db
from app.exceptions import (
    ConflictError,
    NotFoundError,
    UnsupportedFileTypeError,
)
from app.models import FeatureRecord, UploadedFile
from app.schemas import (
    ErrorResponse,
    FeatureMeasurementItem,
    FileDetailResponse,
    FileListItemResponse,
    FileListResponse,
    FileSummary,
    FileUploadResponse,
    GeoJSONFeature,
    GeoJSONFeatureCollection,
    MeasurementDetail,
    PaginatedMeasurementsResponse,
)
from app.services.ingestion import (
    detect_file_type_and_validate,
    save_upload_to_storage,
)
from app.services.processor import process_file

router = APIRouter()


def validate_uuid(id_str: str) -> str:
    """Validate that string is a valid UUID, otherwise raise NotFoundError (404)."""
    try:
        val = uuid.UUID(id_str)
        return str(val)
    except (ValueError, TypeError, AttributeError):
        raise NotFoundError(f"File with id '{id_str}' not found.") from None


def get_file_or_404(file_id: str, db: Session) -> UploadedFile:
    """Retrieve UploadedFile record by ID or raise NotFoundError."""
    clean_id = validate_uuid(file_id)
    file_record = db.query(UploadedFile).filter(UploadedFile.id == clean_id).first()
    if not file_record:
        raise NotFoundError(f"File with id '{file_id}' not found.")
    return file_record


def format_measurement(meas: dict[str, Any] | None) -> MeasurementDetail | None:
    """Format stored raw measurement dict into typed MeasurementDetail schema."""
    if not meas:
        return None
    kind = meas.get("kind")
    val = meas.get("value_si") if "value_si" in meas else meas.get("value")
    unit = meas.get("unit")
    if not unit and kind:
        unit = "m2" if kind == "area" else "m"
    all_units = meas.get("units") or meas.get("all_units") or {}

    return MeasurementDetail(
        kind=kind,
        value=val,
        unit=unit,
        all_units=all_units,
        perimeter=meas.get("perimeter"),
        measurement_crs=meas.get("measurement_crs"),
        method=meas.get("method"),
        geodesic_value=meas.get("geodesic_value"),
        delta_percent=meas.get("delta_percent"),
    )


def process_file_background(file_id: str) -> None:
    """Background task worker with isolated database session."""
    db = SessionLocal()
    try:
        process_file(file_id, db)
    except Exception:
        # process_file catches, updates status to FAILED, and commits
        pass
    finally:
        db.close()


@router.post(
    "",
    include_in_schema=False,
    status_code=status.HTTP_201_CREATED,
    response_model=FileUploadResponse,
)
@router.post(
    "/",
    status_code=status.HTTP_201_CREATED,
    response_model=FileUploadResponse,
    summary="Upload and process geospatial file (.zip Shapefile or .kml)",
    responses={
        201: {"description": "File processed synchronously inline and completed"},
        202: {"description": "File accepted and queued for background processing"},
        400: {"model": ErrorResponse, "description": "Invalid, corrupted, or incomplete archive"},
        413: {"model": ErrorResponse, "description": "File exceeds maximum upload size limit"},
        415: {"model": ErrorResponse, "description": "Unsupported file format or invalid headers"},
    },
)
async def upload_file(
    background_tasks: BackgroundTasks,
    response: Response,
    file: UploadFile = File(..., description="Zipped Shapefile (.zip) or KML (.kml) file"),
    wait: bool = Query(
        default=False,
        description="Force synchronous inline processing even if file size exceeds threshold",
    ),
    db: Session = Depends(get_db),
) -> FileUploadResponse:
    """
    Accept an uploaded .zip (Shapefile archive) or .kml file.

    Processing Strategy:
    - Files below SYNC_PROCESSING_THRESHOLD_BYTES (default 5 MB) or with ?wait=true are processed
      inline and return HTTP 201 with their final status.
    - Files exceeding the threshold are enqueued via BackgroundTasks and return HTTP 202
      with status PENDING.
    """
    filename = file.filename or "unknown_upload"
    ext = Path(filename).suffix.lower()

    if ext not in settings.ALLOWED_EXTENSIONS:
        raise UnsupportedFileTypeError(
            f"Unsupported file extension '{ext}'. Only .zip and .kml files are supported.",
            details={"allowed_extensions": list(settings.ALLOWED_EXTENSIONS)},
        )

    # 1. Stream file to disk enforcing 413 upload size limit
    file_id, saved_path = save_upload_to_storage(file, filename)

    # 2. Inspect magic bytes and file content
    try:
        file_type = detect_file_type_and_validate(saved_path)
    except Exception:
        shutil.rmtree(saved_path.parent, ignore_errors=True)
        raise

    size_bytes = saved_path.stat().st_size

    # 3. Register initial UploadedFile in database
    file_record = UploadedFile(
        id=file_id,
        filename=filename,
        file_type=file_type,
        status="PENDING",
        size_bytes=size_bytes,
        storage_path=str(saved_path),
        feature_count=0,
        warnings=[],
    )
    db.add(file_record)
    db.commit()
    db.refresh(file_record)

    links = {
        "self": f"/api/files/{file_record.id}/",
        "measurements": f"/api/files/{file_record.id}/measurements/",
    }

    # 4. Determine execution path: synchronous inline vs asynchronous background
    is_sync = (size_bytes <= settings.SYNC_PROCESSING_THRESHOLD_BYTES) or wait

    if is_sync:
        process_file(file_record.id, db)
        db.refresh(file_record)
        response.status_code = status.HTTP_201_CREATED
        return FileUploadResponse(
            id=file_record.id,
            filename=file_record.filename,
            status=file_record.status,
            feature_count=file_record.feature_count,
            crs=file_record.crs,
            links=links,
        )

    # Asynchronous background path
    background_tasks.add_task(process_file_background, file_record.id)
    response.status_code = status.HTTP_202_ACCEPTED
    return FileUploadResponse(
        id=file_record.id,
        filename=file_record.filename,
        status="PENDING",
        feature_count=0,
        crs=None,
        links=links,
    )


@router.get(
    "",
    include_in_schema=False,
    response_model=FileListResponse,
)
@router.get(
    "/",
    response_model=FileListResponse,
    summary="List all uploaded geospatial datasets with pagination",
)
def list_files(
    limit: int = Query(default=100, ge=1, le=1000, description="Page limit"),
    offset: int = Query(default=0, ge=0, description="Page offset"),
    db: Session = Depends(get_db),
) -> FileListResponse:
    """Retrieve paginated list of uploaded spatial datasets."""
    total = db.query(UploadedFile).count()
    files = (
        db.query(UploadedFile)
        .order_by(UploadedFile.created_at.desc())
        .offset(offset)
        .limit(limit)
        .all()
    )

    items = [
        FileListItemResponse(
            id=f.id,
            filename=f.filename,
            file_type=f.file_type,
            status=f.status,
            feature_count=f.feature_count,
            crs=f.crs,
            size_bytes=f.size_bytes,
            created_at=f.created_at,
            processed_at=f.processed_at,
            links={
                "self": f"/api/files/{f.id}/",
                "measurements": f"/api/files/{f.id}/measurements/",
            },
        )
        for f in files
    ]

    return FileListResponse(
        total=total,
        limit=limit,
        offset=offset,
        items=items,
    )


@router.get(
    "/{id}",
    include_in_schema=False,
    response_model=FileDetailResponse,
)
@router.get(
    "/{id}/",
    response_model=FileDetailResponse,
    summary="Retrieve detailed metadata and spatial measurement summary for an uploaded file",
    responses={
        404: {"model": ErrorResponse, "description": "File not found or invalid UUID format"},
    },
)
def get_file_detail(
    id: str,
    db: Session = Depends(get_db),
) -> FileDetailResponse:
    """Return dataset metadata, status, geometry breakdown, and aggregate measurement totals."""
    file_record = get_file_or_404(id, db)

    # Geometry type breakdown
    geom_counts = Counter(f.geometry_type for f in file_record.features if f.geometry_type)

    # Status counts
    ok_count = sum(1 for f in file_record.features if f.status == "OK")
    skipped_count = sum(1 for f in file_record.features if f.status == "SKIPPED")
    error_count = sum(1 for f in file_record.features if f.status == "ERROR")

    # Aggregate metric values
    total_area_m2 = 0.0
    total_length_m = 0.0
    for f in file_record.features:
        if f.measurement:
            kind = f.measurement.get("kind")
            val = (
                f.measurement.get("value_si")
                if "value_si" in f.measurement
                else f.measurement.get("value")
            )
            if kind == "area" and isinstance(val, (int, float)):
                total_area_m2 += float(val)
            elif kind == "length" and isinstance(val, (int, float)):
                total_length_m += float(val)

    summary = FileSummary(
        total_area_m2=round(total_area_m2, 4),
        total_length_m=round(total_length_m, 4),
        ok_count=ok_count,
        skipped_count=skipped_count,
        error_count=error_count,
    )

    return FileDetailResponse(
        id=file_record.id,
        filename=file_record.filename,
        feature_count=file_record.feature_count,
        crs=file_record.crs,
        status=file_record.status,
        file_type=file_record.file_type,
        warnings=file_record.warnings or [],
        error=file_record.error,
        created_at=file_record.created_at,
        processed_at=file_record.processed_at,
        geometry_type_counts=dict(geom_counts),
        summary=summary,
    )


@router.get(
    "/{id}/measurements",
    include_in_schema=False,
    response_model=PaginatedMeasurementsResponse,
)
@router.get(
    "/{id}/measurements/",
    summary="Retrieve paginated feature measurements with filtering and GeoJSON export",
    response_model=PaginatedMeasurementsResponse | GeoJSONFeatureCollection,
    responses={
        404: {"model": ErrorResponse, "description": "File not found or invalid UUID format"},
        409: {
            "model": ErrorResponse,
            "description": "File is still in PENDING or PROCESSING status",
        },
    },
)
def get_file_measurements(
    id: str,
    limit: int = Query(default=100, ge=1, le=1000, description="Page limit (max 1000)"),
    offset: int = Query(default=0, ge=0, description="Page offset"),
    geometry_type: str | None = Query(
        default=None,
        description="Filter features by geometry type (e.g. Polygon, LineString, Point)",
    ),
    status: str | None = Query(
        default=None,
        description="Filter features by status (OK, SKIPPED, ERROR)",
    ),
    format: str = Query(
        default="json",
        pattern="^(json|geojson)$",
        description="Response format: 'json' (default) or 'geojson'",
    ),
    db: Session = Depends(get_db),
) -> Any:
    """
    Retrieve measurements for individual features.

    Status Handling:
    - If the file is currently PENDING or PROCESSING, returns HTTP 409 Conflict with a retry notice.
    - If format=geojson, returns a GeoJSON FeatureCollection where measurement details are embedded
      within feature properties.
    """
    file_record = get_file_or_404(id, db)

    if file_record.status in ("PENDING", "PROCESSING"):
        raise ConflictError(
            f"Measurements are not ready yet because file status is '{file_record.status}'. "
            f"Please poll GET /api/files/{id}/ and retry once status is COMPLETED or PARTIAL."
        )

    query = db.query(FeatureRecord).filter(FeatureRecord.file_id == file_record.id)
    if geometry_type:
        query = query.filter(FeatureRecord.geometry_type.ilike(geometry_type))
    if status:
        query = query.filter(FeatureRecord.status == status.upper())

    total_count = query.count()
    records = query.order_by(FeatureRecord.idx).offset(offset).limit(limit).all()

    if format == "geojson":
        features = []
        for feat in records:
            meas_dict = format_measurement(feat.measurement)
            features.append(
                GeoJSONFeature(
                    type="Feature",
                    id=feat.id,
                    geometry=feat.geometry,
                    properties={
                        **feat.properties,
                        "index": feat.idx,
                        "source_layer": feat.source_layer,
                        "geometry_type": feat.geometry_type,
                        "crs": file_record.crs,
                        "status": feat.status,
                        "warnings": feat.warnings or [],
                        "measurement": meas_dict.model_dump() if meas_dict else None,
                    },
                )
            )
        return GeoJSONFeatureCollection(
            type="FeatureCollection",
            total=total_count,
            limit=limit,
            offset=offset,
            features=features,
        )

    # Standard JSON format
    items = [
        FeatureMeasurementItem(
            index=feat.idx,
            geometry_type=feat.geometry_type,
            geometry=feat.geometry,
            crs=file_record.crs,
            properties=feat.properties or {},
            status=feat.status,
            warnings=feat.warnings or [],
            measurement=format_measurement(feat.measurement),
        )
        for feat in records
    ]

    return PaginatedMeasurementsResponse(
        total=total_count,
        limit=limit,
        offset=offset,
        items=items,
    )


@router.delete(
    "/{id}",
    include_in_schema=False,
)
@router.delete(
    "/{id}/",
    summary="Delete an uploaded dataset, its feature records, and stored files on disk",
    responses={
        404: {"model": ErrorResponse, "description": "File not found or invalid UUID format"},
    },
)
def delete_file(
    id: str,
    db: Session = Depends(get_db),
) -> dict[str, str]:
    """Delete uploaded dataset, associated feature records, and file system storage."""
    file_record = get_file_or_404(id, db)
    file_id = file_record.id

    # Clean up disk files
    if file_record.storage_path:
        storage_p = Path(file_record.storage_path)
        if storage_p.exists():
            shutil.rmtree(storage_p.parent, ignore_errors=True)

    target_dir = settings.UPLOAD_DIR / file_id
    if target_dir.exists():
        shutil.rmtree(target_dir, ignore_errors=True)

    # Cascade delete in database
    db.delete(file_record)
    db.commit()

    return {
        "id": file_id,
        "message": "File and associated records deleted successfully.",
    }
