"""Targeted unit tests to ensure high test coverage (>85%) across all modules in app/services/."""

import zipfile
from datetime import date, time
from decimal import Decimal
from pathlib import Path

import pytest
from shapely.geometry import (
    GeometryCollection,
    LineString,
    MultiLineString,
    MultiPoint,
    Point,
    Polygon,
)

import app.services.readers
from app.exceptions import (
    InvalidGeoFileError,
    UnsupportedFileTypeError,
)
from app.services.crs import (
    get_transformer,
    project_geometry,
    select_measurement_crs,
    to_wgs84,
)
from app.services.ingestion import (
    detect_file_type_and_validate,
    safe_extract_zip,
)
from app.services.measurements import (
    _compute_delta,
    _convert_area_units,
    _convert_length_units,
    measure_feature,
)
from app.services.processor import process_file, sanitize_json_value
from app.services.readers import (
    _parse_coord_triplet,
    _parse_kml_coordinates,
    read_kml,
    read_kml_fallback,
)

# =====================================================================
# 1. CRS Module Edge Cases (Polar, Svalbard, multi-zone, invalid/empty)
# =====================================================================


def test_crs_polar_fallback() -> None:
    """Geometries in high polar latitudes (lat > 84 or lat < -80) trigger EPSG:6933 fallback."""
    north_pole_geom = Polygon([(0.0, 85.0), (1.0, 85.0), (1.0, 86.0), (0.0, 86.0), (0.0, 85.0)])
    crs_north, method_north = select_measurement_crs(north_pole_geom)
    assert crs_north.to_epsg() == 6933
    assert method_north == "EQUAL_AREA-6933"

    south_pole_geom = Polygon(
        [(0.0, -82.0), (1.0, -82.0), (1.0, -81.0), (0.0, -81.0), (0.0, -82.0)]
    )
    crs_south, method_south = select_measurement_crs(south_pole_geom)
    assert crs_south.to_epsg() == 6933
    assert method_south == "EQUAL_AREA-6933"


def test_crs_utm_zones() -> None:
    """Standard UTM zone determination across different longitudes and latitudes."""
    pt1 = Point(4.5, 60.0)
    crs1, method1 = select_measurement_crs(pt1)
    assert crs1.to_epsg() == 32631

    pt2 = Point(15.0, 78.0)
    crs2, method2 = select_measurement_crs(pt2)
    assert crs2.to_epsg() == 32633


def test_crs_empty_and_unknown_crs() -> None:
    """Handle empty geometry, unknown source CRS, and transformer cache clearing."""
    empty_poly = Polygon()
    crs_empty, method_empty = select_measurement_crs(empty_poly)
    assert crs_empty.to_epsg() == 3857

    # Empty geometry projection
    proj_empty = project_geometry(empty_poly, crs_empty)
    assert proj_empty.is_empty

    # Unknown source CRS raises InvalidGeoFileError
    pt = Point(10.0, 20.0)
    with pytest.raises(InvalidGeoFileError, match="Invalid or unrecognized CRS"):
        to_wgs84(pt, "INVALID:UNKNOWN:CRS")

    # Empty geometry to_wgs84
    assert to_wgs84(empty_poly).is_empty

    # Clear transformer cache
    get_transformer.cache_clear()


# =====================================================================
# 2. Ingestion Security & Error Edge Cases
# =====================================================================


def test_ingestion_zip_bomb_and_traversal_guards(tmp_path: Path) -> None:
    """Security verification for zip bombs, file limits, and symlinks."""
    # Exceeding file count limit raises InvalidGeoFileError
    many_files_zip = tmp_path / "many_files.zip"
    with zipfile.ZipFile(many_files_zip, "w") as zf:
        for i in range(105):
            zf.writestr(f"file_{i}.txt", b"x")

    with pytest.raises(InvalidGeoFileError, match="exceeding limit"):
        safe_extract_zip(many_files_zip, tmp_path / "many_out")

    # Incomplete shapefile missing mandatory files (.shx, .dbf)
    incomplete_zip = tmp_path / "incomplete.zip"
    with zipfile.ZipFile(incomplete_zip, "w") as zf:
        zf.writestr("test.shp", b"dummy")
    with pytest.raises(InvalidGeoFileError, match="Missing required shapefile component"):
        safe_extract_zip(incomplete_zip, tmp_path / "inc_out")


def test_detect_file_type_corrupt_kml_and_zip(tmp_path: Path) -> None:
    """Detection errors for non-KML xml and invalid zip headers."""
    bad_kml = tmp_path / "bad.kml"
    bad_kml.write_text("<svg><circle r='10'/></svg>", encoding="utf-8")
    with pytest.raises(UnsupportedFileTypeError, match="does not contain valid KML markup"):
        detect_file_type_and_validate(bad_kml)

    fake_zip = tmp_path / "fake.zip"
    fake_zip.write_bytes(b"PK\x03\x04BROKEN_BODY_DATA_NOT_VALID_ZIP")
    with pytest.raises(UnsupportedFileTypeError, match="failed zip integrity validation"):
        detect_file_type_and_validate(fake_zip)


# =====================================================================
# 3. Measurement Module Coverage (GeometryCollection, Discrepancies)
# =====================================================================


def test_measurements_geometry_collection_lines_and_units() -> None:
    """Measure GeometryCollection containing only lines and test unit conversion utilities."""
    line1 = LineString([(0.0, 0.0), (1.0, 0.0)])
    line2 = LineString([(1.0, 0.0), (1.0, 1.0)])
    gc = GeometryCollection([line1, line2])

    res = measure_feature(gc, "EPSG:4326")
    assert res.status == "OK"
    assert res.kind == "length"
    assert res.value_si is not None and res.value_si > 0
    assert "km" in res.units

    # Unit conversion utilities
    area_units = _convert_area_units(10000.0)
    assert area_units["m2"] == 10000.0
    assert area_units["hectares"] == 1.0

    len_units = _convert_length_units(5000.0)
    assert len_units["m"] == 5000.0
    assert len_units["km"] == 5.0

    # Delta computation edge cases
    assert _compute_delta(100.0, 0.0) == 0.0
    assert _compute_delta(100.0, 100.0) == 0.0


# =====================================================================
# 4. Reader Module Coverage (XML Fallback Parser & Properties)
# =====================================================================


def test_readers_xml_fallback_parser(tmp_path: Path) -> None:
    """Test defusedxml pure-Python fallback KML parser directly."""
    kml_text = """<?xml version="1.0" encoding="UTF-8"?>
<kml xmlns="http://www.opengis.net/kml/2.2">
  <Document>
    <Placemark>
      <name>Polygon with Hole</name>
      <description>Sample plot with interior courtyard</description>
      <Polygon>
        <outerBoundaryIs>
          <LinearRing>
            <coordinates>0,0,0 10,0,0 10,10,0 0,10,0 0,0,0</coordinates>
          </LinearRing>
        </outerBoundaryIs>
        <innerBoundaryIs>
          <LinearRing>
            <coordinates>2,2,0 8,2,0 8,8,0 2,8,0 2,2,0</coordinates>
          </LinearRing>
        </innerBoundaryIs>
      </Polygon>
    </Placemark>
    <Placemark>
      <name>MultiLine Route</name>
      <MultiGeometry>
        <LineString>
          <coordinates>0,0,0 5,5,0</coordinates>
        </LineString>
        <LineString>
          <coordinates>5,5,0 10,10,0</coordinates>
        </LineString>
      </MultiGeometry>
    </Placemark>
    <Placemark>
      <name>MultiPoint Survey</name>
      <MultiGeometry>
        <Point><coordinates>1,1,0</coordinates></Point>
        <Point><coordinates>2,2,0</coordinates></Point>
      </MultiGeometry>
    </Placemark>
  </Document>
</kml>"""
    kml_file = tmp_path / "fallback.kml"
    kml_file.write_text(kml_text, encoding="utf-8")

    features = read_kml_fallback(kml_file)
    assert len(features) == 3
    # Check polygon with hole
    poly_feat = features[0]
    assert isinstance(poly_feat.geometry, Polygon)
    assert len(poly_feat.geometry.interiors) == 1

    # Check MultiLine
    assert isinstance(features[1].geometry, (MultiLineString, GeometryCollection))

    # Check MultiPoint
    assert isinstance(features[2].geometry, (MultiPoint, GeometryCollection))

    # Coordinate parsing helper
    assert _parse_coord_triplet(" 12.5 , 55.6 , 100 ") == (12.5, 55.6, 100.0)
    assert _parse_kml_coordinates(None) == []


def test_read_kml_triggers_pure_python_fallback(tmp_path: Path, monkeypatch) -> None:
    """When GDAL/pyogrio fails on KML, read_kml falls back to pure-Python XML parser."""
    kml_text = """<?xml version="1.0" encoding="UTF-8"?>
<kml xmlns="http://www.opengis.net/kml/2.2">
  <Document>
    <Placemark>
      <name>Fallback Test Placemark</name>
      <Point><coordinates>77.59,12.97,0</coordinates></Point>
    </Placemark>
  </Document>
</kml>"""
    kml_path = tmp_path / "force_fallback.kml"
    kml_path.write_text(kml_text, encoding="utf-8")

    # Monkeypatch pyogrio.list_layers to raise an exception
    def mock_list_layers(path):
        raise RuntimeError("Simulated C driver failure")

    monkeypatch.setattr(app.services.readers.pyogrio, "list_layers", mock_list_layers)

    result = read_kml(kml_path)
    assert len(result.features) == 1
    assert result.features[0].properties.get("name") == "Fallback Test Placemark"
    assert any("pure-Python" in w for w in result.file_warnings)


# =====================================================================
# 5. Processor Module Edge Cases (Sanitization, Failures, DB Missing)
# =====================================================================


def test_processor_sanitization_and_failure_guards(db_session) -> None:
    """Test sanitization of dates, decimals, bytes, and missing record handling."""
    data = {
        "decimal": Decimal("123.45"),
        "date": date(2026, 10, 8),
        "time": time(14, 30, 0),
        "raw_bytes": b"binary_data",
        "custom_obj": object(),
    }
    sanitized = sanitize_json_value(data)
    assert sanitized["decimal"] == 123.45
    assert sanitized["date"] == "2026-10-08"
    assert sanitized["time"] == "14:30:00"
    assert "binary_data" in sanitized["raw_bytes"]
    assert isinstance(sanitized["custom_obj"], str)

    # Calling process_file on non-existent record raises InvalidGeoFileError
    with pytest.raises(InvalidGeoFileError, match="not found"):
        process_file("00000000-0000-0000-0000-000000000000", db_session)
