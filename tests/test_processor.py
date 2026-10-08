"""Integration tests for the spatial processor pipeline, persistence, and status lifecycle."""

from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path

import pytest
from sqlalchemy.orm import Session

from app.exceptions import InvalidGeoFileError
from app.models import FeatureRecord, UploadedFile
from app.services.processor import process_file, sanitize_json_value


def test_sanitize_json_value_types() -> None:
    """Ensure non-standard types, NaNs, Decimals, bytes, and timestamps are sanitized for JSON."""
    raw = {
        "nan_val": float("nan"),
        "inf_val": float("inf"),
        "decimal_val": Decimal("123.45"),
        "byte_val": b"heritage_site",
        "date_val": datetime(2026, 10, 8, 12, 0, tzinfo=UTC),
        "nested": {
            "list_val": [float("nan"), 42, "text"],
        },
    }

    clean = sanitize_json_value(raw)
    assert clean["nan_val"] is None
    assert clean["inf_val"] is None
    assert clean["decimal_val"] == 123.45
    assert clean["byte_val"] == "heritage_site"
    assert "2026-10-08" in clean["date_val"]
    assert clean["nested"]["list_val"] == [None, 42, "text"]


def test_process_good_file_lifecycle(
    valid_shapefile_zip: Path,
    db_session: Session,
) -> None:
    """A valid spatial file transitions from PENDING -> COMPLETED with persisted features."""
    record = UploadedFile(
        filename="parcels.zip",
        file_type="shapefile_zip",
        status="PENDING",
        size_bytes=valid_shapefile_zip.stat().st_size,
        storage_path=str(valid_shapefile_zip),
    )
    db_session.add(record)
    db_session.commit()
    db_session.refresh(record)

    assert record.status == "PENDING"
    assert record.processed_at is None

    completed_file = process_file(record.id, db_session)

    assert completed_file.status == "COMPLETED"
    assert completed_file.feature_count == 1
    assert completed_file.processed_at is not None
    assert completed_file.error is None
    assert completed_file.crs is not None

    # Verify persisted FeatureRecords
    features = db_session.query(FeatureRecord).filter(FeatureRecord.file_id == record.id).all()
    assert len(features) == 1
    f0 = features[0]
    assert f0.status == "OK"
    assert f0.source_layer == "parcels"
    assert f0.geometry_type == "Polygon"
    assert f0.geometry is not None
    assert "coordinates" in f0.geometry
    assert f0.measurement is not None
    assert f0.measurement["kind"] == "area"
    assert f0.measurement["value_si"] > 0


def test_process_mixed_file_with_null_geometry(
    shapefile_with_null_geom_zip: Path,
    db_session: Session,
) -> None:
    """
    A file with mixed geometries (1 valid polygon + 1 null/empty) finishes as COMPLETED,
    with the valid feature marked OK and the null feature marked SKIPPED.
    """
    record = UploadedFile(
        filename="mixed.zip",
        file_type="shapefile_zip",
        status="PENDING",
        size_bytes=shapefile_with_null_geom_zip.stat().st_size,
        storage_path=str(shapefile_with_null_geom_zip),
    )
    db_session.add(record)
    db_session.commit()
    db_session.refresh(record)

    completed_file = process_file(record.id, db_session)

    assert completed_file.status == "COMPLETED"
    assert completed_file.feature_count == 2
    assert completed_file.processed_at is not None

    features = (
        db_session.query(FeatureRecord)
        .filter(FeatureRecord.file_id == record.id)
        .order_by(FeatureRecord.idx)
        .all()
    )
    assert len(features) == 2
    assert features[0].status == "OK"
    assert features[0].measurement is not None

    assert features[1].status == "SKIPPED"
    assert features[1].measurement is None
    assert any("Empty or null geometry" in w for w in features[1].warnings)


def test_process_corrupt_file_sets_failed_status(
    corrupt_zip_file: Path,
    db_session: Session,
) -> None:
    """A corrupt file must transition to FAILED and record an informative error message."""
    record = UploadedFile(
        filename="corrupt.zip",
        file_type="shapefile_zip",
        status="PENDING",
        size_bytes=corrupt_zip_file.stat().st_size,
        storage_path=str(corrupt_zip_file),
    )
    db_session.add(record)
    db_session.commit()
    db_session.refresh(record)

    with pytest.raises(InvalidGeoFileError):
        process_file(record.id, db_session)

    # Re-query record from DB
    db_session.expire_all()
    failed_file = db_session.query(UploadedFile).filter(UploadedFile.id == record.id).first()

    assert failed_file is not None
    assert failed_file.status == "FAILED"
    assert failed_file.error is not None
    assert len(failed_file.error) > 0
    assert failed_file.processed_at is not None


def test_never_left_in_processing_state(
    valid_shapefile_zip: Path,
    db_session: Session,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Even if an unexpected system exception occurs, file is never left in PROCESSING."""
    record = UploadedFile(
        filename="failover.zip",
        file_type="shapefile_zip",
        status="PENDING",
        size_bytes=valid_shapefile_zip.stat().st_size,
        storage_path=str(valid_shapefile_zip),
    )
    db_session.add(record)
    db_session.commit()

    # Simulate an unexpected critical crash inside read_shapefiles
    def _crash(*args: object, **kwargs: object) -> None:
        raise RuntimeError("Unexpected simulated system memory exhaustion")

    monkeypatch.setattr("app.services.processor.read_shapefiles", _crash)

    with pytest.raises(RuntimeError):
        process_file(record.id, db_session)

    db_session.expire_all()
    persisted = db_session.query(UploadedFile).filter(UploadedFile.id == record.id).first()

    assert persisted is not None
    assert persisted.status == "FAILED"
    assert "Unexpected simulated system memory exhaustion" in str(persisted.error)
    assert persisted.processed_at is not None
