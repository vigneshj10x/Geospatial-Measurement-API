"""Unit and integration tests for file ingestion, zip security, and geospatial readers."""

from io import BytesIO
from pathlib import Path

import pytest

from app.config import settings
from app.exceptions import (
    FileTooLargeError,
    InvalidGeoFileError,
    UnsupportedFileTypeError,
)
from app.services.ingestion import (
    detect_file_type_and_validate,
    safe_extract_zip,
    save_upload_to_storage,
)
from app.services.readers import read_kml, read_shapefiles


def test_valid_shapefile_zip_ingestion_and_reading(
    valid_shapefile_zip: Path,
    tmp_path: Path,
) -> None:
    """A valid shapefile zip passes type detection, extraction, and reading."""
    fmt = detect_file_type_and_validate(valid_shapefile_zip)
    assert fmt == "shapefile_zip"

    extract_dir = tmp_path / "extracted_valid"
    shp_paths = safe_extract_zip(valid_shapefile_zip, extract_dir)
    assert len(shp_paths) == 1
    assert shp_paths[0].name == "parcels.shp"

    result = read_shapefiles(shp_paths)
    assert len(result.features) == 1
    feat = result.features[0]
    assert feat.status == "VALID"
    assert feat.source_layer == "parcels"
    assert feat.geometry is not None
    assert feat.measurement_geometry is not None
    assert feat.geometry.geom_type == "Polygon"
    assert not feat.measurement_geometry.has_z


def test_valid_kml_ingestion_and_reading(valid_kml_file: Path) -> None:
    """A valid KML file passes type detection and yields features with Z-coordinates stripped."""
    fmt = detect_file_type_and_validate(valid_kml_file)
    assert fmt == "kml"

    result = read_kml(valid_kml_file)
    assert result.crs == "EPSG:4326"
    assert len(result.features) == 2

    poly_feat = result.features[0]
    assert poly_feat.status == "VALID"
    assert poly_feat.properties.get("name") == "Eiffel Tower Parcel"
    # Original geometry had 3D coordinates (z=35)
    assert poly_feat.geometry is not None
    assert poly_feat.geometry.has_z is True
    # Measurement geometry must have Z coordinates dropped
    assert poly_feat.measurement_geometry is not None
    assert poly_feat.measurement_geometry.has_z is False

    point_feat = result.features[1]
    assert point_feat.status == "VALID"
    assert point_feat.measurement_geometry is not None
    assert not point_feat.measurement_geometry.has_z


def test_zip_slip_rejection(zip_slip_archive: Path, tmp_path: Path) -> None:
    """Archives with directory traversal (zip-slip) paths must be blocked."""
    extract_dir = tmp_path / "extracted_slip"
    with pytest.raises(InvalidGeoFileError) as exc_info:
        safe_extract_zip(zip_slip_archive, extract_dir)
    assert "zip-slip" in str(exc_info.value).lower() or "traversal" in str(exc_info.value).lower()


def test_missing_dbf_rejection(shapefile_missing_dbf_zip: Path, tmp_path: Path) -> None:
    """Missing .dbf component must raise a clear 400 error naming the missing file."""
    extract_dir = tmp_path / "extracted_no_dbf"
    with pytest.raises(InvalidGeoFileError) as exc_info:
        safe_extract_zip(shapefile_missing_dbf_zip, extract_dir)

    err_msg = str(exc_info.value)
    assert ".dbf" in err_msg
    assert "Missing required shapefile component" in err_msg


def test_corrupt_zip_rejection(corrupt_zip_file: Path, tmp_path: Path) -> None:
    """Corrupted binary files with .zip extensions must be rejected."""
    with pytest.raises(UnsupportedFileTypeError):
        detect_file_type_and_validate(corrupt_zip_file)

    extract_dir = tmp_path / "extracted_corrupt"
    with pytest.raises(InvalidGeoFileError):
        safe_extract_zip(corrupt_zip_file, extract_dir)


def test_wrong_extension_rejection(wrong_extension_file: Path) -> None:
    """Files with unsupported extensions must raise UnsupportedFileTypeError (415)."""
    with pytest.raises(UnsupportedFileTypeError) as exc_info:
        detect_file_type_and_validate(wrong_extension_file)
    assert exc_info.value.status_code == 415


def test_oversized_file_rejection(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Uploading files larger than MAX_UPLOAD_SIZE_BYTES must raise FileTooLargeError (413)."""
    # Temporarily set limit to 100 KB for rapid testing
    monkeypatch.setattr(settings, "MAX_UPLOAD_SIZE_BYTES", 100 * 1024)

    large_payload = BytesIO(b"X" * (150 * 1024))
    storage_dir = tmp_path / "uploads_test"

    with pytest.raises(FileTooLargeError) as exc_info:
        save_upload_to_storage(large_payload, "oversized.zip", custom_storage_dir=storage_dir)

    assert exc_info.value.status_code == 413
    assert "exceeds maximum allowed size" in str(exc_info.value)


def test_shapefile_missing_prj_handling(
    shapefile_missing_prj_zip: Path,
    tmp_path: Path,
) -> None:
    """Missing .prj assumes EPSG:4326 and adds a file-level warning."""
    extract_dir = tmp_path / "extracted_no_prj"
    shp_paths = safe_extract_zip(shapefile_missing_prj_zip, extract_dir)

    result = read_shapefiles(shp_paths)
    assert result.crs == "EPSG:4326"
    assert any("No .prj found; assumed EPSG:4326" in w for w in result.file_warnings)
    assert len(result.features) == 1
    assert result.features[0].status == "VALID"


def test_shapefile_with_null_geometry_handling(
    shapefile_with_null_geom_zip: Path,
    tmp_path: Path,
) -> None:
    """Null/empty geometries must not be dropped silently; mark as SKIPPED with warning."""
    extract_dir = tmp_path / "extracted_null_geom"
    shp_paths = safe_extract_zip(shapefile_with_null_geom_zip, extract_dir)

    result = read_shapefiles(shp_paths)
    assert len(result.features) == 2

    valid_f = result.features[0]
    assert valid_f.status == "VALID"
    assert valid_f.geometry is not None

    empty_f = result.features[1]
    assert empty_f.status == "SKIPPED"
    assert any("Empty or null geometry" in w for w in empty_f.warnings)


def test_multi_shapefile_layer_tagging(
    multi_shapefile_zip: Path,
    tmp_path: Path,
) -> None:
    """Multiple shapefiles in an archive are processed and tagged with their source layer."""
    extract_dir = tmp_path / "extracted_multi"
    shp_paths = safe_extract_zip(multi_shapefile_zip, extract_dir)
    assert len(shp_paths) == 2

    result = read_shapefiles(shp_paths)
    assert len(result.features) == 2

    layers = {f.source_layer for f in result.features}
    assert "parcels" in layers
    assert "trails" in layers


def test_multi_folder_kml_reading(multi_folder_kml_file: Path) -> None:
    """KML with multiple folders/layers processes all features and tags source layers."""
    result = read_kml(multi_folder_kml_file)
    assert len(result.features) == 2

    layers = {f.source_layer for f in result.features}
    assert "Northern_Reserve" in layers
    assert "Southern_Trail" in layers
