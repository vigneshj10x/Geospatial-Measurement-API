"""End-to-end geospatial processing pipeline with persistence and status management."""

import math
import time as perf_timer
from dataclasses import asdict
from datetime import UTC, date, datetime, time
from decimal import Decimal
from pathlib import Path
from typing import Any

import shapely.geometry
from sqlalchemy.orm import Session

from app.exceptions import InvalidGeoFileError
from app.logger import logger
from app.models import FeatureRecord, UploadedFile
from app.services.ingestion import safe_extract_zip
from app.services.measurements import measure_feature
from app.services.readers import read_kml, read_shapefiles


def sanitize_json_value(val: Any) -> Any:
    """
    Recursively sanitize values to ensure 100% JSON-serializable primitives.

    Handles:
    - NaN / Infinity -> None
    - NumPy scalars and arrays -> standard Python types
    - datetime / date / time / pd.Timestamp -> ISO-8601 strings
    - Decimal -> float
    - raw bytes (common in shapefile dBase tables) -> utf-8 decoded string
    - sets / tuples -> lists
    """
    if val is None:
        return None

    # Floats / Ints
    if isinstance(val, (float, int)):
        if isinstance(val, float) and (math.isnan(val) or math.isinf(val)):
            return None
        return val

    # Dates and Times
    if isinstance(val, (datetime, date, time)):
        return val.isoformat()

    # Decimals
    if isinstance(val, Decimal):
        f = float(val)
        return None if (math.isnan(f) or math.isinf(f)) else f

    # Raw bytes from binary fields
    if isinstance(val, bytes):
        return val.decode("utf-8", errors="replace")

    # NumPy scalars
    if hasattr(val, "item"):
        scalar = val.item()
        if isinstance(scalar, float) and (math.isnan(scalar) or math.isinf(scalar)):
            return None
        if isinstance(scalar, (datetime, date)):
            return scalar.isoformat()
        return scalar

    # NumPy arrays or series
    if hasattr(val, "tolist"):
        return [sanitize_json_value(x) for x in val.tolist()]

    # Sequences
    if isinstance(val, (list, tuple, set)):
        return [sanitize_json_value(x) for x in val]

    # Dictionaries
    if isinstance(val, dict):
        return {str(k): sanitize_json_value(v) for k, v in val.items()}

    return str(val) if not isinstance(val, (str, bool)) else val


def process_file(
    file_id: str,
    db: Session,
    storage_path: Path | None = None,
) -> UploadedFile:
    """
    Process an uploaded spatial file end-to-end:
    1. Sets status to 'PROCESSING' and commits.
    2. Uses try/finally to guarantee the file is NEVER left in 'PROCESSING'.
    3. Runs secure archive extraction / KML discovery and unified reader.
    4. Measures every feature with isolated per-feature error boundary.
    5. Bulk inserts FeatureRecords.
    6. Computes final status:
       - 'COMPLETED': all features OK or SKIPPED-by-design (points / empty).
       - 'PARTIAL': some features processed OK/SKIPPED but some encountered ERROR.
       - 'FAILED': file was unreadable, corrupted, or 0 features succeeded.
    7. Records processed_at timestamp and persists all records.
    """
    uploaded_file = db.query(UploadedFile).filter(UploadedFile.id == file_id).first()
    if not uploaded_file:
        raise InvalidGeoFileError(f"Uploaded file record '{file_id}' not found.")

    uploaded_file.status = "PROCESSING"
    uploaded_file.error = None
    db.commit()

    start_total = perf_timer.perf_counter()
    file_failed_error: str | None = None

    try:
        source_path = storage_path or Path(uploaded_file.storage_path or "")
        if not source_path.exists():
            raise InvalidGeoFileError(
                f"Source file not found at storage path: {source_path}",
                details={"storage_path": str(source_path)},
            )

        # 1. Ingestion & Reading
        t0_read = perf_timer.perf_counter()
        if uploaded_file.file_type == "shapefile_zip":
            extract_dir = source_path.parent / "extracted"
            shp_paths = safe_extract_zip(source_path, extract_dir)
            read_result = read_shapefiles(shp_paths)
        elif uploaded_file.file_type == "kml":
            read_result = read_kml(source_path)
        else:
            raise InvalidGeoFileError(
                f"Unsupported file format: {uploaded_file.file_type}",
                details={"file_type": uploaded_file.file_type},
            )
        read_ms = round((perf_timer.perf_counter() - t0_read) * 1000, 2)
        logger.info(
            f"File '{file_id}' read stage complete: "
            f"{len(read_result.features)} features in {read_ms}ms"
        )

        feature_records: list[FeatureRecord] = []
        t0_meas = perf_timer.perf_counter()

        # 2. Per-feature isolated processing
        for feat in read_result.features:
            feat_warnings = list(feat.warnings)

            try:
                # If feature already marked SKIPPED by reader (e.g. null geometry)
                if feat.status == "SKIPPED":
                    meas_dict = None
                    final_feat_status = "SKIPPED"
                else:
                    # Run measurement engine
                    meas_result = measure_feature(
                        feat.measurement_geometry,
                        source_crs_input=read_result.crs,
                    )
                    meas_dict = asdict(meas_result) if meas_result.kind is not None else None
                    feat_warnings.extend(meas_result.warnings)

                    if meas_result.status == "ERROR":
                        final_feat_status = "ERROR"
                    elif meas_result.status == "SKIPPED":
                        final_feat_status = "SKIPPED"
                    else:
                        final_feat_status = "OK"

                # Extract GeoJSON representation in ORIGINAL CRS via shapely.geometry.mapping
                if feat.geometry is not None and not feat.geometry.is_empty:
                    geom_mapping = shapely.geometry.mapping(feat.geometry)
                else:
                    geom_mapping = None

                # Geometry type
                geom_type = feat.geometry.geom_type if feat.geometry is not None else "None"

                rec = FeatureRecord(
                    file_id=uploaded_file.id,
                    idx=feat.index,
                    source_layer=feat.source_layer,
                    geometry_type=geom_type,
                    geometry=sanitize_json_value(geom_mapping),
                    properties=sanitize_json_value(feat.properties),
                    status=final_feat_status,
                    warnings=sanitize_json_value(feat_warnings),
                    measurement=sanitize_json_value(meas_dict),
                )
            except Exception as feat_err:
                # Isolated error boundary: a single broken feature never aborts the batch
                rec = FeatureRecord(
                    file_id=uploaded_file.id,
                    idx=feat.index,
                    source_layer=feat.source_layer,
                    geometry_type="Unknown",
                    geometry=None,
                    properties=sanitize_json_value(feat.properties),
                    status="ERROR",
                    warnings=[f"Feature measurement error: {feat_err}"],
                    measurement=None,
                )

            feature_records.append(rec)

        meas_ms = round((perf_timer.perf_counter() - t0_meas) * 1000, 2)
        logger.info(
            f"File '{file_id}' measurement stage complete: {len(feature_records)} features "
            f"processed in {meas_ms}ms"
        )

        # 3. Bulk insert FeatureRecords
        t0_db = perf_timer.perf_counter()
        db.add_all(feature_records)

        # 4. Compute final file status
        num_errors = sum(1 for f in feature_records if f.status == "ERROR")
        num_ok = sum(1 for f in feature_records if f.status == "OK")
        num_skipped = sum(1 for f in feature_records if f.status == "SKIPPED")

        if num_errors > 0 and (num_ok > 0 or num_skipped > 0):
            uploaded_file.status = "PARTIAL"
        elif num_errors > 0 and num_ok == 0 and num_skipped == 0:
            uploaded_file.status = "FAILED"
            uploaded_file.error = "All features encountered processing errors."
        else:
            uploaded_file.status = "COMPLETED"

        total_ms = round((perf_timer.perf_counter() - start_total) * 1000, 2)
        uploaded_file.feature_count = len(feature_records)
        uploaded_file.crs = read_result.crs
        uploaded_file.warnings = sanitize_json_value(read_result.file_warnings)
        uploaded_file.processed_at = datetime.now(UTC)
        uploaded_file.processing_duration_ms = total_ms
        db.commit()
        db.refresh(uploaded_file)

        db_ms = round((perf_timer.perf_counter() - t0_db) * 1000, 2)
        logger.info(
            f"File '{file_id}' db persistence complete in {db_ms}ms. "
            f"Total duration: {total_ms}ms, Status: {uploaded_file.status}"
        )
        return uploaded_file

    except Exception as exc:
        total_ms = round((perf_timer.perf_counter() - start_total) * 1000, 2)
        file_failed_error = str(exc)
        uploaded_file.status = "FAILED"
        uploaded_file.error = file_failed_error
        uploaded_file.processed_at = datetime.now(UTC)
        uploaded_file.processing_duration_ms = total_ms
        db.commit()
        db.refresh(uploaded_file)
        logger.error(
            f"File '{file_id}' processing failed after {total_ms}ms: {exc}"
        )
        raise

    finally:
        # Guarantee: File is never left stuck in PROCESSING
        if uploaded_file.status == "PROCESSING":
            uploaded_file.status = "FAILED"
            uploaded_file.error = file_failed_error or "Processing aborted unexpectedly."
            uploaded_file.processed_at = datetime.now(UTC)
            uploaded_file.processing_duration_ms = round(
                (perf_timer.perf_counter() - start_total) * 1000, 2
            )
            db.commit()
