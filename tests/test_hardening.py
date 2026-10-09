"""Hardening, stress testing, and edge case test suite for geospatial measurement API."""

import time
import zipfile
from pathlib import Path

import geopandas as gpd
import pytest
from shapely.geometry import LineString, Point, Polygon
from starlette.testclient import TestClient

import app.services.processor


def test_end_to_end_ground_truth_verification(client: TestClient, tmp_path: Path) -> None:
    """E2E test: upload -> info -> measurements, verifying exact known area and length."""
    # 100m x 100m square in UTM Zone 31N (EPSG:32631) -> Area exactly 10,000 m2, perimeter 400 m
    poly = Polygon(
        [
            (500000.0, 1000000.0),
            (500100.0, 1000000.0),
            (500100.0, 1000100.0),
            (500000.0, 1000100.0),
            (500000.0, 1000000.0),
        ]
    )
    # 500m straight line -> Length exactly 500 m
    line = LineString([(500000.0, 1000000.0), (500500.0, 1000000.0)])

    gdf_poly = gpd.GeoDataFrame(
        [{"name": "Known Square 1ha", "category": "parcel", "geometry": poly}],
        crs="EPSG:32631",
    )
    gdf_line = gpd.GeoDataFrame(
        [{"name": "Known Line 500m", "category": "road", "geometry": line}],
        crs="EPSG:32631",
    )

    src_dir = tmp_path / "ground_truth_source"
    src_dir.mkdir(parents=True, exist_ok=True)
    gdf_poly.to_file(src_dir / "parcels.shp", engine="pyogrio")
    gdf_line.to_file(src_dir / "roads.shp", engine="pyogrio")

    zip_path = tmp_path / "ground_truth.zip"
    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
        for f in src_dir.iterdir():
            zf.write(f, arcname=f.name)

    # 1. POST upload
    with open(zip_path, "rb") as f:
        up_res = client.post(
            "/api/files/",
            files={"file": (zip_path.name, f, "application/zip")},
        )
    assert up_res.status_code == 201
    file_id = up_res.json()["id"]

    # 2. GET info
    info_res = client.get(f"/api/files/{file_id}/")
    assert info_res.status_code == 200
    info = info_res.json()
    assert info["status"] == "COMPLETED"
    assert info["feature_count"] == 2
    assert info["crs"] == "EPSG:32631"

    summary = info["summary"]
    # Verify exact known numbers
    assert pytest.approx(summary["total_area_m2"], rel=1e-3) == 10000.0
    assert pytest.approx(summary["total_length_m"], rel=1e-3) == 500.0
    assert summary["ok_count"] == 2
    assert summary["skipped_count"] == 0
    assert summary["error_count"] == 0

    # 3. GET measurements
    meas_res = client.get(f"/api/files/{file_id}/measurements/")
    assert meas_res.status_code == 200
    items = meas_res.json()["items"]
    assert len(items) == 2

    # Verify polygon measurement details
    poly_item = items[0]
    assert poly_item["geometry_type"] == "Polygon"
    assert poly_item["status"] == "OK"
    meas_poly = poly_item["measurement"]
    assert meas_poly["kind"] == "area"
    assert pytest.approx(meas_poly["value"], rel=1e-3) == 10000.0
    assert pytest.approx(meas_poly["perimeter"], rel=1e-3) == 400.0
    assert pytest.approx(meas_poly["all_units"]["hectares"], rel=1e-3) == 1.0
    assert pytest.approx(meas_poly["all_units"]["km2"], rel=1e-3) == 0.01

    # Verify line measurement details
    line_item = items[1]
    assert line_item["geometry_type"] == "LineString"
    assert line_item["status"] == "OK"
    meas_line = line_item["measurement"]
    assert meas_line["kind"] == "length"
    assert pytest.approx(meas_line["value"], rel=1e-3) == 500.0
    assert pytest.approx(meas_line["all_units"]["km"], rel=1e-3) == 0.5


def test_mixed_geometry_types(client: TestClient) -> None:
    """Test sample file with mixed geometry types: Polygons, Lines, and Points."""
    sample_path = Path("samples/mixed_geometries.zip")
    assert sample_path.exists(), "samples/mixed_geometries.zip must exist"

    with open(sample_path, "rb") as f:
        up_res = client.post(
            "/api/files/",
            files={"file": (sample_path.name, f, "application/zip")},
        )
    assert up_res.status_code == 201
    file_id = up_res.json()["id"]

    info_res = client.get(f"/api/files/{file_id}/")
    assert info_res.status_code == 200
    info = info_res.json()
    assert info["status"] == "COMPLETED"
    assert info["feature_count"] == 5  # 2 polygons + 1 line + 2 points

    geom_counts = info["geometry_type_counts"]
    assert geom_counts.get("Polygon") == 2
    assert geom_counts.get("LineString") == 1
    assert geom_counts.get("Point") == 2

    summary = info["summary"]
    assert summary["ok_count"] == 5  # 2 polys + 1 line + 2 points
    assert summary["skipped_count"] == 0  # Points are OK with no measurement
    assert summary["error_count"] == 0
    assert summary["total_area_m2"] > 0
    assert summary["total_length_m"] > 0


def test_file_with_only_points(client: TestClient, tmp_path: Path) -> None:
    """File containing only points is COMPLETED with ok_count = N and zero area/length."""
    gdf = gpd.GeoDataFrame(
        [
            {"station": "ST-A", "geometry": Point(77.59, 12.97)},
            {"station": "ST-B", "geometry": Point(77.60, 12.98)},
            {"station": "ST-C", "geometry": Point(77.61, 12.99)},
        ],
        crs="EPSG:4326",
    )
    src_dir = tmp_path / "points_source"
    src_dir.mkdir(parents=True, exist_ok=True)
    gdf.to_file(src_dir / "stations.shp", engine="pyogrio")

    zip_path = tmp_path / "stations.zip"
    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
        for f in src_dir.iterdir():
            zf.write(f, arcname=f.name)

    with open(zip_path, "rb") as f:
        up_res = client.post(
            "/api/files/",
            files={"file": (zip_path.name, f, "application/zip")},
        )
    assert up_res.status_code == 201
    file_id = up_res.json()["id"]

    info_res = client.get(f"/api/files/{file_id}/")
    info = info_res.json()
    assert info["status"] == "COMPLETED"
    assert info["feature_count"] == 3
    assert info["geometry_type_counts"] == {"Point": 3}

    summary = info["summary"]
    assert summary["ok_count"] == 3
    assert summary["skipped_count"] == 0
    assert summary["error_count"] == 0
    assert summary["total_area_m2"] == 0.0
    assert summary["total_length_m"] == 0.0


def test_partial_status_scenario(client: TestClient, tmp_path: Path, monkeypatch) -> None:
    """When some features succeed and one feature errors out, status becomes PARTIAL."""
    poly1 = Polygon([(0.0, 0.0), (1.0, 0.0), (1.0, 1.0), (0.0, 1.0), (0.0, 0.0)])
    poly2 = Polygon([(2.0, 2.0), (3.0, 2.0), (3.0, 3.0), (2.0, 3.0), (2.0, 2.0)])
    gdf = gpd.GeoDataFrame(
        [
            {"name": "Valid 1", "geometry": poly1},
            {"name": "To Fail", "geometry": poly2},
        ],
        crs="EPSG:4326",
    )
    src_dir = tmp_path / "partial_source"
    src_dir.mkdir(parents=True, exist_ok=True)
    gdf.to_file(src_dir / "partial.shp", engine="pyogrio")

    zip_path = tmp_path / "partial.zip"
    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
        for f in src_dir.iterdir():
            zf.write(f, arcname=f.name)

    # Monkeypatch measure_feature to fail on the second feature
    original_measure = app.services.processor.measure_feature

    def mock_measure_feature(geom, source_crs_input=None):
        if geom is not None and getattr(geom, "bounds", None) and geom.bounds[0] >= 2.0:
            raise ValueError("Deliberate calculation failure for test")
        return original_measure(geom, source_crs_input=source_crs_input)

    monkeypatch.setattr(app.services.processor, "measure_feature", mock_measure_feature)

    with open(zip_path, "rb") as f:
        up_res = client.post(
            "/api/files/",
            files={"file": (zip_path.name, f, "application/zip")},
        )
    assert up_res.status_code == 201
    file_id = up_res.json()["id"]

    info_res = client.get(f"/api/files/{file_id}/")
    info = info_res.json()
    assert info["status"] == "PARTIAL"
    assert info["summary"]["ok_count"] == 1
    assert info["summary"]["error_count"] == 1

    meas_res = client.get(f"/api/files/{file_id}/measurements/")
    items = meas_res.json()["items"]
    assert items[0]["status"] == "OK"
    assert items[1]["status"] == "ERROR"
    assert any("Deliberate calculation failure" in w for w in items[1]["warnings"])


def test_unicode_attribute_names_and_values(client: TestClient, tmp_path: Path) -> None:
    """Unicode attributes (Hindi, Kannada, Japanese, accents) are preserved throughout pipeline."""
    poly = Polygon([(77.58, 12.96), (77.59, 12.96), (77.59, 12.97), (77.58, 12.97), (77.58, 12.96)])
    gdf = gpd.GeoDataFrame(
        [
            {
                "proprio": "René & Zoë",
                "locality": "ಬೆಂಗಳೂರು",
                "desc": "शांति और प्रगति",
                "geometry": poly,
            }
        ],
        crs="EPSG:4326",
    )
    src_dir = tmp_path / "unicode_source"
    src_dir.mkdir(parents=True, exist_ok=True)
    gdf.to_file(src_dir / "unicode.shp", engine="pyogrio")

    zip_path = tmp_path / "unicode.zip"
    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
        for f in src_dir.iterdir():
            zf.write(f, arcname=f.name)

    with open(zip_path, "rb") as f:
        up_res = client.post(
            "/api/files/",
            files={"file": (zip_path.name, f, "application/zip")},
        )
    assert up_res.status_code == 201
    file_id = up_res.json()["id"]

    meas_res = client.get(f"/api/files/{file_id}/measurements/")
    props = meas_res.json()["items"][0]["properties"]
    assert props["proprio"] == "René & Zoë"
    assert props["locality"] == "ಬೆಂಗಳೂರು"
    assert props["desc"] == "शांति और प्रगति"


def test_missing_prj_generates_warning(client: TestClient, shapefile_missing_prj_zip: Path) -> None:
    """Missing .prj defaults to EPSG:4326 with an explicit warning recorded in the response."""
    with open(shapefile_missing_prj_zip, "rb") as f:
        up_res = client.post(
            "/api/files/",
            files={"file": (shapefile_missing_prj_zip.name, f, "application/zip")},
        )
    assert up_res.status_code == 201
    file_id = up_res.json()["id"]

    info_res = client.get(f"/api/files/{file_id}/")
    info = info_res.json()
    assert info["status"] == "COMPLETED"
    assert info["crs"] == "EPSG:4326"
    assert any("defaulted to EPSG:4326" in w for w in info["warnings"])


def test_large_file_5000_polygons_performance(client: TestClient, tmp_path: Path) -> None:
    """Upload and process 5,000 polygons to verify bulk pipeline throughput and responsiveness."""
    # Generate 5,000 distinct small polygons
    polys = []
    names = []
    for i in range(5000):
        x = (i % 100) * 0.005 + 10.0
        y = (i // 100) * 0.005 + 50.0
        p = Polygon([(x, y), (x + 0.003, y), (x + 0.003, y + 0.003), (x, y + 0.003), (x, y)])
        polys.append(p)
        names.append(f"Plot-{i}")

    gdf = gpd.GeoDataFrame({"plot_id": names, "geometry": polys}, crs="EPSG:4326")
    src_dir = tmp_path / "large_source"
    src_dir.mkdir(parents=True, exist_ok=True)
    gdf.to_file(src_dir / "large.shp", engine="pyogrio")

    zip_path = tmp_path / "large_5000.zip"
    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
        for f in src_dir.iterdir():
            zf.write(f, arcname=f.name)

    start_time = time.perf_counter()
    with open(zip_path, "rb") as f:
        up_res = client.post(
            "/api/files/?wait=true",
            files={"file": (zip_path.name, f, "application/zip")},
        )
    duration = time.perf_counter() - start_time

    assert up_res.status_code == 201
    data = up_res.json()
    assert data["status"] == "COMPLETED"
    assert data["feature_count"] == 5000

    # Ensure acceptable execution time (5,000 features processed and persisted in reasonable time)
    print(f"5,000 features processed in {duration:.2f}s (throughput: {5000 / duration:.1f} feat/s)")
    assert duration < 30.0, f"Processing 5,000 polygons took too long: {duration:.2f}s"

    file_id = data["id"]
    meas_res = client.get(f"/api/files/{file_id}/measurements/?limit=50")
    assert meas_res.status_code == 200
    meas_data = meas_res.json()
    assert meas_data["total"] == 5000
    assert len(meas_data["items"]) == 50
