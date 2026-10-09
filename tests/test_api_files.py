"""REST API integration tests for upload, status tracking, measurements, filtering, and deletion."""

from pathlib import Path

from starlette.testclient import TestClient

from app.config import settings
from app.models import UploadedFile


def test_upload_shapefile_zip_sync(client: TestClient, valid_shapefile_zip: Path) -> None:
    """Synchronous upload of a valid Shapefile archive should process and return 201."""
    with open(valid_shapefile_zip, "rb") as f:
        response = client.post(
            "/api/files/",
            files={"file": (valid_shapefile_zip.name, f, "application/zip")},
        )
    assert response.status_code == 201
    data = response.json()
    assert data["filename"] == valid_shapefile_zip.name
    assert data["status"] == "COMPLETED"
    assert data["feature_count"] == 1
    assert data["crs"] == "EPSG:4326"
    assert "links" in data
    assert f"/api/files/{data['id']}/" in data["links"]["self"]
    assert f"/api/files/{data['id']}/measurements/" in data["links"]["measurements"]


def test_upload_kml_sync(client: TestClient, valid_kml_file: Path) -> None:
    """Synchronous upload of a valid KML file should process features and return 201."""
    with open(valid_kml_file, "rb") as f:
        response = client.post(
            "/api/files/",
            files={"file": (valid_kml_file.name, f, "application/vnd.google-earth.kml+xml")},
        )
    assert response.status_code == 201
    data = response.json()
    assert data["status"] == "COMPLETED"
    assert data["feature_count"] == 2
    assert data["crs"] == "EPSG:4326"


def test_get_file_detail(client: TestClient, valid_kml_file: Path) -> None:
    """GET /api/files/{id}/ returns detailed metadata and summary statistics."""
    with open(valid_kml_file, "rb") as f:
        up_res = client.post(
            "/api/files/",
            files={"file": (valid_kml_file.name, f, "application/vnd.google-earth.kml+xml")},
        )
    file_id = up_res.json()["id"]

    res = client.get(f"/api/files/{file_id}/")
    assert res.status_code == 200
    detail = res.json()
    assert detail["id"] == file_id
    assert detail["feature_count"] == 2
    assert detail["status"] == "COMPLETED"
    assert "geometry_type_counts" in detail
    assert detail["geometry_type_counts"].get("Polygon") == 1
    assert detail["geometry_type_counts"].get("Point") == 1

    summary = detail["summary"]
    assert summary["ok_count"] == 2  # Polygon measured OK, Point status OK
    assert summary["skipped_count"] == 0
    assert summary["error_count"] == 0
    assert summary["total_area_m2"] > 0.0
    assert summary["total_length_m"] == 0.0


def test_get_measurements_json_and_pagination(
    client: TestClient, multi_shapefile_zip: Path
) -> None:
    """GET /api/files/{id}/measurements/ returns paginated measurements with SI units."""
    with open(multi_shapefile_zip, "rb") as f:
        up_res = client.post(
            "/api/files/",
            files={"file": (multi_shapefile_zip.name, f, "application/zip")},
        )
    file_id = up_res.json()["id"]

    # Request first page limit=1
    res = client.get(f"/api/files/{file_id}/measurements/?limit=1&offset=0")
    assert res.status_code == 200
    data = res.json()
    assert data["total"] == 2
    assert data["limit"] == 1
    assert data["offset"] == 0
    assert len(data["items"]) == 1

    first_item = data["items"][0]
    assert "index" in first_item
    assert "geometry_type" in first_item
    assert "geometry" in first_item
    assert first_item["geometry"]["type"] in ("Polygon", "LineString")
    assert "crs" in first_item
    assert "status" in first_item
    assert "measurement" in first_item

    meas = first_item["measurement"]
    assert meas is not None
    assert meas["kind"] in ("area", "length")
    assert meas["value"] > 0
    assert "all_units" in meas
    assert "measurement_crs" in meas
    assert "method" in meas
    assert "geodesic_value" in meas
    assert "delta_percent" in meas


def test_get_measurements_filtering(client: TestClient, multi_shapefile_zip: Path) -> None:
    """Filter measurements by geometry_type and status."""
    with open(multi_shapefile_zip, "rb") as f:
        up_res = client.post(
            "/api/files/",
            files={"file": (multi_shapefile_zip.name, f, "application/zip")},
        )
    file_id = up_res.json()["id"]

    # Filter Polygon
    res_poly = client.get(f"/api/files/{file_id}/measurements/?geometry_type=Polygon")
    assert res_poly.status_code == 200
    poly_data = res_poly.json()
    assert poly_data["total"] == 1
    assert poly_data["items"][0]["geometry_type"] == "Polygon"

    # Filter LineString
    res_line = client.get(f"/api/files/{file_id}/measurements/?geometry_type=LineString")
    assert res_line.status_code == 200
    line_data = res_line.json()
    assert line_data["total"] == 1
    assert line_data["items"][0]["geometry_type"] == "LineString"

    # Filter status OK
    res_status = client.get(f"/api/files/{file_id}/measurements/?status=OK")
    assert res_status.status_code == 200
    assert res_status.json()["total"] == 2


def test_get_measurements_geojson_format(client: TestClient, valid_shapefile_zip: Path) -> None:
    """GET /api/files/{id}/measurements/?format=geojson returns a valid FeatureCollection."""
    with open(valid_shapefile_zip, "rb") as f:
        up_res = client.post(
            "/api/files/",
            files={"file": (valid_shapefile_zip.name, f, "application/zip")},
        )
    file_id = up_res.json()["id"]

    res = client.get(f"/api/files/{file_id}/measurements/?format=geojson")
    assert res.status_code == 200
    fc = res.json()
    assert fc["type"] == "FeatureCollection"
    assert fc["total"] == 1
    assert len(fc["features"]) == 1

    feature = fc["features"][0]
    assert feature["type"] == "Feature"
    assert feature["geometry"]["type"] == "Polygon"
    assert "properties" in feature
    props = feature["properties"]
    assert "measurement" in props
    assert props["measurement"]["kind"] == "area"
    assert props["measurement"]["value"] > 0
    assert "status" in props
    assert props["status"] == "OK"


def test_measurements_conflict_409_when_processing(client: TestClient, db_session) -> None:
    """Requesting measurements for a file in PENDING or PROCESSING status returns HTTP 409."""
    pending_file = UploadedFile(
        id="99999999-9999-9999-9999-999999999999",
        filename="queued.zip",
        file_type="shapefile_zip",
        status="PROCESSING",
        feature_count=0,
        size_bytes=1024,
    )
    db_session.add(pending_file)
    db_session.commit()

    res = client.get(f"/api/files/{pending_file.id}/measurements/")
    assert res.status_code == 409
    body = res.json()
    assert body["error"]["code"] == "CONFLICT"
    assert "PROCESSING" in body["error"]["message"]


def test_not_found_404_handling(client: TestClient) -> None:
    """Non-existent IDs and invalid UUID formats yield consistent 404 error responses."""
    # Invalid UUID string
    res_inv = client.get("/api/files/not-a-valid-uuid/")
    assert res_inv.status_code == 404
    assert res_inv.json()["error"]["code"] == "NOT_FOUND"

    # Valid UUID but not found in DB
    res_missing = client.get("/api/files/00000000-0000-0000-0000-000000000000/")
    assert res_missing.status_code == 404
    assert res_missing.json()["error"]["code"] == "NOT_FOUND"

    # Missing file measurements
    res_meas = client.get("/api/files/00000000-0000-0000-0000-000000000000/measurements/")
    assert res_meas.status_code == 404
    assert res_meas.json()["error"]["code"] == "NOT_FOUND"

    # Missing file delete
    res_del = client.delete("/api/files/00000000-0000-0000-0000-000000000000/")
    assert res_del.status_code == 404
    assert res_del.json()["error"]["code"] == "NOT_FOUND"


def test_unsupported_file_type_415(
    client: TestClient, wrong_extension_file: Path, corrupt_zip_file: Path
) -> None:
    """Uploading unsupported extensions or archives lacking valid magic signatures raises 415."""
    # Unsupported extension (.geojson)
    with open(wrong_extension_file, "rb") as f:
        res = client.post(
            "/api/files/",
            files={"file": (wrong_extension_file.name, f, "application/json")},
        )
    assert res.status_code == 415
    assert res.json()["error"]["code"] == "UNSUPPORTED_FILE_TYPE"

    # .zip extension with fake plain-text header
    with open(corrupt_zip_file, "rb") as f:
        res2 = client.post(
            "/api/files/",
            files={"file": (corrupt_zip_file.name, f, "application/zip")},
        )
    assert res2.status_code == 415
    assert res2.json()["error"]["code"] == "UNSUPPORTED_FILE_TYPE"


def test_file_too_large_413(client: TestClient, valid_shapefile_zip: Path, monkeypatch) -> None:
    """Files exceeding MAX_UPLOAD_SIZE_BYTES are halted immediately with HTTP 413."""
    monkeypatch.setattr(settings, "MAX_UPLOAD_SIZE_BYTES", 50)
    with open(valid_shapefile_zip, "rb") as f:
        res = client.post(
            "/api/files/",
            files={"file": (valid_shapefile_zip.name, f, "application/zip")},
        )
    assert res.status_code == 413
    assert res.json()["error"]["code"] == "FILE_TOO_LARGE"


def test_corrupt_shapefile_missing_dbf_400(
    client: TestClient, shapefile_missing_dbf_zip: Path
) -> None:
    """Uploading a shapefile archive missing mandatory components raises 400 INVALID_GEO_FILE."""
    with open(shapefile_missing_dbf_zip, "rb") as f:
        res = client.post(
            "/api/files/",
            files={"file": (shapefile_missing_dbf_zip.name, f, "application/zip")},
        )
    assert res.status_code == 400
    assert res.json()["error"]["code"] == "INVALID_GEO_FILE"


def test_background_processing_path(
    client: TestClient, valid_shapefile_zip: Path, monkeypatch
) -> None:
    """Files exceeding threshold return 202 PENDING unless ?wait=true is passed."""
    # Set threshold to 0 so every file exceeds the limit
    monkeypatch.setattr(settings, "SYNC_PROCESSING_THRESHOLD_BYTES", 0)

    # 1. Async background scheduling -> 202 ACCEPTED
    with open(valid_shapefile_zip, "rb") as f:
        res_async = client.post(
            "/api/files/",
            files={"file": (valid_shapefile_zip.name, f, "application/zip")},
        )
    assert res_async.status_code == 202
    assert res_async.json()["status"] == "PENDING"

    # 2. Forced synchronous with ?wait=true -> 201 CREATED
    with open(valid_shapefile_zip, "rb") as f2:
        res_sync = client.post(
            "/api/files/?wait=true",
            files={"file": (valid_shapefile_zip.name, f2, "application/zip")},
        )
    assert res_sync.status_code == 201
    assert res_sync.json()["status"] == "COMPLETED"


def test_list_files_paginated(client: TestClient, valid_kml_file: Path) -> None:
    """GET /api/files/ returns paginated list of uploaded files."""
    with open(valid_kml_file, "rb") as f:
        client.post(
            "/api/files/",
            files={"file": (valid_kml_file.name, f, "application/vnd.google-earth.kml+xml")},
        )

    res = client.get("/api/files/?limit=10&offset=0")
    assert res.status_code == 200
    data = res.json()
    assert data["total"] >= 1
    assert len(data["items"]) >= 1
    item = data["items"][0]
    assert "id" in item
    assert "filename" in item
    assert "links" in item


def test_delete_file(client: TestClient, valid_shapefile_zip: Path) -> None:
    """DELETE /api/files/{id}/ removes database rows and deletes disk files."""
    with open(valid_shapefile_zip, "rb") as f:
        up_res = client.post(
            "/api/files/",
            files={"file": (valid_shapefile_zip.name, f, "application/zip")},
        )
    file_id = up_res.json()["id"]

    # Confirm it exists
    assert client.get(f"/api/files/{file_id}/").status_code == 200

    # Delete
    del_res = client.delete(f"/api/files/{file_id}/")
    assert del_res.status_code == 200
    assert del_res.json()["id"] == file_id

    # Verify 404 after deletion
    assert client.get(f"/api/files/{file_id}/").status_code == 404
