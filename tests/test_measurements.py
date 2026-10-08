"""Rigorous unit and accuracy tests for the geospatial measurement engine.

Covers:
- Metric precision against known geodesic ground truths (~1km² parcel, 1° equatorial arc).
- Naive degree vs. metric projection comparison.
- Adaptive UTM and Lambert Azimuthal Equal-Area (LAEA) zone selection.
- Southern hemisphere, multi-zone, and large feature handling.
- Complex geometries (holes, MultiPolygon, GeometryCollection, self-intersecting bowtie).
- Graceful handling of Points, empty geometries, and pre-projected CRS inputs.
"""

import pytest
from shapely import ops
from shapely.geometry import (
    GeometryCollection,
    LineString,
    MultiPolygon,
    Point,
    Polygon,
)

from app.services.crs import get_transformer
from app.services.measurements import measure_feature


def test_known_1km_square_area_accuracy() -> None:
    """
    A 1,000m x 1,000m parcel created in projected UTM space (EPSG:32631) and converted
    to WGS84 must measure within 0.1% of the true 1,000,000 m² area.
    """
    # 1,000m x 1,000m square in UTM Zone 31N meters
    utm_poly = Polygon(
        [
            (500_000.0, 5_000_000.0),
            (501_000.0, 5_000_000.0),
            (501_000.0, 5_001_000.0),
            (500_000.0, 5_001_000.0),
            (500_000.0, 5_000_000.0),
        ]
    )
    assert utm_poly.area == 1_000_000.0

    # Transform to WGS84 (EPSG:4326)
    transformer = get_transformer("EPSG:32631", "EPSG:4326")
    wgs84_poly = ops.transform(transformer.transform, utm_poly)

    res = measure_feature(wgs84_poly, source_crs_input="EPSG:4326")
    assert res.status == "OK"
    assert res.kind == "area"
    assert res.value_si is not None

    # Verify area is within 0.1% (1,000 m²) of 1,000,000 m²
    assert abs(res.value_si - 1_000_000.0) / 1_000_000.0 < 0.001
    assert res.units["m2"] == res.value_si
    assert pytest.approx(res.units["hectares"], rel=1e-3) == 100.0
    assert pytest.approx(res.units["square_kilometers"], rel=1e-3) == 1.0

    # Geodesic cross-check agreement
    assert res.geodesic_value is not None
    assert res.delta_percent is not None
    assert res.delta_percent < 0.1


def test_known_one_degree_equatorial_longitude_length() -> None:
    """
    On the WGS84 ellipsoid at the equator (latitude 0.0), 1 degree of longitude
    corresponds to approximately 111,319.5 meters:
    a * pi / 180 = 6,378,137.0 * pi / 180 ≈ 111,319.49 m.
    """
    equator_line = LineString([(0.0, 0.0), (1.0, 0.0)])
    res = measure_feature(equator_line, source_crs_input="EPSG:4326")

    assert res.status == "OK"
    assert res.kind == "length"
    assert res.value_si is not None

    # Expected value is ~111,319 m; assert agreement within 0.1%
    assert abs(res.value_si - 111_319.49) / 111_319.49 < 0.001
    assert res.geodesic_value is not None
    assert abs(res.geodesic_value - 111_319.49) < 2.0
    assert res.delta_percent is not None
    assert res.delta_percent < 0.1


def test_naive_degree_area_vs_projected_area_demonstration() -> None:
    """
    Demonstrates why computing area in degrees is fundamentally invalid.

    In geographic coordinates (EPSG:4326), coordinates are angular angles on a sphere/ellipsoid,
    not planar distances.
    1. A degree of latitude is roughly constant (~111 km), but 1 degree of longitude shrinks
       with latitude proportional to cos(lat) - dropping to 0 at the poles.
    2. Shapely's `polygon.area` on unprojected WGS84 coordinates computes degrees² (deg²),
       a meaningless unit for physical terrain.
    3. For our 1,000,000 m² (1 km²) parcel in France (lat ~45°N), the naive degree area
       is ~0.000115 deg². If directly used or naively multiplied by a constant, it produces
       catastrophic errors exceeding hundreds of percent compared to proper metric projections.
    """
    # 1km x 1km parcel in France
    utm_poly = Polygon(
        [
            (500_000.0, 5_000_000.0),
            (501_000.0, 5_000_000.0),
            (501_000.0, 5_001_000.0),
            (500_000.0, 5_001_000.0),
            (500_000.0, 5_000_000.0),
        ]
    )
    transformer = get_transformer("EPSG:32631", "EPSG:4326")
    wgs84_poly = ops.transform(transformer.transform, utm_poly)

    # Naive degree-squared calculation
    naive_deg2_area = wgs84_poly.area
    # True metric area via our projection engine
    res = measure_feature(wgs84_poly, source_crs_input="EPSG:4326")

    # In degrees², the value is ~0.000115 deg²
    assert naive_deg2_area < 0.001
    # In m², the value is ~1,000,000 m²
    assert res.value_si is not None
    assert res.value_si > 990_000.0

    # The ratio between true m² and naive deg² is nearly 10 orders of magnitude!
    ratio = res.value_si / naive_deg2_area
    assert ratio > 1_000_000_000.0


def test_southern_hemisphere_utm_selection() -> None:
    """Features in the southern hemisphere must select southern UTM zones (EPSG:327xx)."""
    # Parcel near Sydney, Australia: ~151.2°E, -33.86°S (UTM Zone 56S -> EPSG:32756)
    sydney_poly = Polygon(
        [
            (151.20, -33.86),
            (151.21, -33.86),
            (151.21, -33.85),
            (151.20, -33.85),
            (151.20, -33.86),
        ]
    )
    res = measure_feature(sydney_poly)
    assert res.status == "OK"
    assert "32756" in res.method
    assert "EPSG:32756" in res.measurement_crs
    assert res.value_si is not None and res.value_si > 0
    assert res.delta_percent is not None and res.delta_percent < 0.2


def test_feature_straddling_utm_zone_boundary() -> None:
    """
    A feature that straddles the boundary between two UTM zones (e.g. 5.9°E to 6.1°E,
    crossing the 6.0° boundary between UTM 31 and UTM 32) must fall back to LAEA.
    """
    straddle_poly = Polygon(
        [
            (5.90, 48.00),
            (6.10, 48.00),
            (6.10, 48.10),
            (5.90, 48.10),
            (5.90, 48.00),
        ]
    )
    res = measure_feature(straddle_poly)
    assert res.status == "OK"
    assert res.method == "LAEA-local"
    assert "+proj=laea" in res.measurement_crs
    assert res.value_si is not None and res.value_si > 0
    assert res.delta_percent is not None and res.delta_percent < 0.2


def test_large_feature_spanning_multiple_zones() -> None:
    """A feature spanning over 6 degrees longitude triggers the LAEA equal-area fallback."""
    wide_poly = Polygon(
        [
            (-5.0, 40.0),
            (3.0, 40.0),
            (3.0, 42.0),
            (-5.0, 42.0),
            (-5.0, 40.0),
        ]
    )
    res = measure_feature(wide_poly)
    assert res.status == "OK"
    assert res.method == "LAEA-local"
    assert "+proj=laea" in res.measurement_crs
    assert res.value_si is not None and res.value_si > 0
    assert res.delta_percent is not None and res.delta_percent < 0.5


def test_polygon_with_interior_hole() -> None:
    """A polygon with an interior hole must have the hole's area subtracted naturally."""
    exterior = [(0.0, 0.0), (0.1, 0.0), (0.1, 0.1), (0.0, 0.1), (0.0, 0.0)]
    interior = [(0.02, 0.02), (0.04, 0.02), (0.04, 0.04), (0.02, 0.04), (0.02, 0.02)]

    donut = Polygon(exterior, holes=[interior])
    solid = Polygon(exterior)

    res_donut = measure_feature(donut)
    res_solid = measure_feature(solid)

    assert res_donut.status == "OK"
    assert res_solid.status == "OK"
    assert res_donut.value_si is not None and res_solid.value_si is not None

    # Donut area must be strictly less than solid area
    assert res_donut.value_si < res_solid.value_si

    # Geodesic check must also agree with the hole subtraction
    assert res_donut.delta_percent is not None and res_donut.delta_percent < 0.2


def test_multipolygon_measurement() -> None:
    """MultiPolygons are measured by summing component areas and perimeter."""
    poly1 = Polygon([(0.0, 0.0), (0.02, 0.0), (0.02, 0.02), (0.0, 0.02), (0.0, 0.0)])
    poly2 = Polygon([(0.04, 0.04), (0.06, 0.04), (0.06, 0.06), (0.04, 0.06), (0.04, 0.04)])
    multipoly = MultiPolygon([poly1, poly2])

    res = measure_feature(multipoly)
    assert res.status == "OK"
    assert res.kind == "area"

    res1 = measure_feature(poly1)
    res2 = measure_feature(poly2)

    assert res.value_si is not None and res1.value_si is not None and res2.value_si is not None
    assert pytest.approx(res.value_si, rel=1e-3) == (res1.value_si + res2.value_si)
    assert res.delta_percent is not None and res.delta_percent < 0.2


def test_point_geometry_returns_no_measurement() -> None:
    """Point geometries return status SKIPPED by design, kind None, and no measurements."""
    pt = Point(12.5, 55.6)
    res = measure_feature(pt)
    assert res.status == "SKIPPED"
    assert res.kind is None
    assert res.value_si is None
    assert res.units == {}
    assert res.geodesic_value is None
    assert res.delta_percent is None


def test_geometry_collection_aggregation() -> None:
    """GeometryCollection aggregates supported polygon and line members and warns on points."""
    poly = Polygon([(0.0, 0.0), (0.02, 0.0), (0.02, 0.02), (0.0, 0.02), (0.0, 0.0)])
    line = LineString([(0.0, 0.0), (0.02, 0.02)])
    pt = Point(0.01, 0.01)

    collection = GeometryCollection([poly, line, pt])
    res = measure_feature(collection)

    assert res.status == "OK"
    assert res.kind == "area"
    assert res.value_si is not None and res.value_si > 0
    assert any("Point member" in w for w in res.warnings)


def test_invalid_bowtie_polygon_repaired() -> None:
    """Self-intersecting bowtie polygon is repaired via make_valid with warning added."""
    bowtie = Polygon([(0.0, 0.0), (0.02, 0.02), (0.02, 0.0), (0.0, 0.02), (0.0, 0.0)])
    assert not bowtie.is_valid

    res = measure_feature(bowtie)
    assert res.status == "OK"
    assert res.kind == "area"
    assert res.value_si is not None and res.value_si > 0
    assert any("geometry repaired" in w for w in res.warnings)
    assert res.delta_percent is not None and res.delta_percent < 0.2


def test_empty_geometry_skipped() -> None:
    """Empty geometry returns status SKIPPED without raising an exception."""
    empty_poly = Polygon()
    res = measure_feature(empty_poly)
    assert res.status == "SKIPPED"
    assert res.kind is None
    assert any("empty or null" in w.lower() for w in res.warnings)


def test_pre_projected_crs_input_handling() -> None:
    """Geometries provided already in a projected CRS (e.g. EPSG:32643) measure correctly."""
    # 1,000m x 1,000m parcel defined in UTM Zone 43N meters
    poly_32643 = Polygon(
        [
            (500_000.0, 2_000_000.0),
            (501_000.0, 2_000_000.0),
            (501_000.0, 2_001_000.0),
            (500_000.0, 2_001_000.0),
            (500_000.0, 2_000_000.0),
        ]
    )

    res = measure_feature(poly_32643, source_crs_input="EPSG:32643")
    assert res.status == "OK"
    assert res.kind == "area"
    assert res.value_si is not None

    # Must equal 1,000,000 m² within 0.1%
    assert abs(res.value_si - 1_000_000.0) / 1_000_000.0 < 0.001
    assert res.delta_percent is not None and res.delta_percent < 0.1
