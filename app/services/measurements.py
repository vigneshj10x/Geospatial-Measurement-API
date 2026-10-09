"""High-precision geospatial measurement engine with adaptive CRS and geodesic cross-checks."""

from dataclasses import dataclass, field
from typing import Any

import pyproj
import shapely
from shapely.geometry import (
    GeometryCollection,
    LinearRing,
    LineString,
    MultiLineString,
    MultiPoint,
    MultiPolygon,
    Point,
    Polygon,
)
from shapely.geometry.base import BaseGeometry

from app.services.crs import (
    project_geometry,
    select_measurement_crs,
    to_wgs84,
)
from app.services.units import (
    convert_area_units,
    convert_length_units,
)

# Reference WGS84 Geoid
WGS84_GEOD = pyproj.Geod(ellps="WGS84")

# Conversion constants
M2_TO_HECTARES = 1e-4
M2_TO_ACRES = 1.0 / 4046.8564224
M2_TO_KM2 = 1e-6

METERS_TO_KM = 1e-3
METERS_TO_MILES = 1.0 / 1609.344

# Backward-compatibility internal aliases
_convert_area_units = convert_area_units
_convert_length_units = convert_length_units


@dataclass
class MeasurementResult:
    """Standardized measurement outcome for a single spatial feature."""

    kind: str | None
    value_si: float | None
    units: dict[str, float]
    perimeter: float | None
    measurement_crs: str
    method: str
    geodesic_value: float | None
    delta_percent: float | None
    warnings: list[str] = field(default_factory=list)
    status: str = "OK"


def _compute_delta(projected: float, geodesic: float) -> float:
    """Calculate relative percentage difference between projected and geodesic values."""
    if geodesic <= 0.0:
        return 0.0
    return round((abs(projected - geodesic) / geodesic) * 100.0, 4)


def _calculate_geodesic_polygon_area(poly: Polygon) -> float:
    """Calculate net geodesic area of a Polygon ensuring holes are subtracted correctly."""
    outer_area, _ = WGS84_GEOD.geometry_area_perimeter(Polygon(poly.exterior))
    net_area = abs(outer_area)
    for hole in poly.interiors:
        hole_area, _ = WGS84_GEOD.geometry_area_perimeter(Polygon(hole))
        net_area -= abs(hole_area)
    return max(0.0, net_area)


def _calculate_geodesic_area_perimeter(geom: Polygon | MultiPolygon) -> tuple[float, float]:
    """Calculate net geodesic area and perimeter for Polygon or MultiPolygon."""
    if isinstance(geom, Polygon):
        area = _calculate_geodesic_polygon_area(geom)
        _, perim = WGS84_GEOD.geometry_area_perimeter(geom)
        return area, abs(perim)
    if isinstance(geom, MultiPolygon):
        total_area = sum(_calculate_geodesic_polygon_area(p) for p in geom.geoms)
        _, perim = WGS84_GEOD.geometry_area_perimeter(geom)
        return total_area, abs(perim)
    return 0.0, 0.0


def _extract_polygons(geom: BaseGeometry) -> list[Polygon]:
    """Recursively extract all Polygon parts from collections and multi-geometries."""
    polys: list[Polygon] = []
    if isinstance(geom, Polygon):
        polys.append(geom)
    elif isinstance(geom, MultiPolygon):
        polys.extend(geom.geoms)
    elif isinstance(geom, GeometryCollection):
        for part in geom.geoms:
            polys.extend(_extract_polygons(part))
    return polys


def _extract_lines(geom: BaseGeometry) -> list[LineString | LinearRing]:
    """Recursively extract all linear parts from collections and multi-geometries."""
    lines: list[LineString | LinearRing] = []
    if isinstance(geom, (LineString, LinearRing)):
        lines.append(geom)
    elif isinstance(geom, MultiLineString):
        lines.extend(geom.geoms)
    elif isinstance(geom, GeometryCollection):
        for part in geom.geoms:
            lines.extend(_extract_lines(part))
    return lines


def measure_feature(
    geom: BaseGeometry | None,
    source_crs_input: Any = "EPSG:4326",
) -> MeasurementResult:
    """
    Measure an individual feature geometry:
    1. Normalizes coordinates to WGS84 (EPSG:4326).
    2. Repairs invalid geometries via shapely.make_valid.
    3. Adaptively chooses optimal projected CRS (UTM / LAEA / equal-area).
    4. Computes planar metric area/length and independent geodesic cross-check.
    5. Returns MeasurementResult with status 'OK', 'SKIPPED', or 'ERROR'.
    """
    warnings: list[str] = []

    # 1. Null / None / Empty check
    if geom is None or not isinstance(geom, BaseGeometry) or geom.is_empty:
        return MeasurementResult(
            kind=None,
            value_si=None,
            units={},
            perimeter=None,
            measurement_crs="None",
            method="None",
            geodesic_value=None,
            delta_percent=None,
            warnings=["Feature geometry is empty or null."],
            status="SKIPPED",
        )

    try:
        # 2. Convert to WGS84 for zone selection and geodesic checks
        geom_wgs84 = to_wgs84(geom, source_crs_input)

        # 3. Handle Points / MultiPoints: No measurement by spec, status OK
        if isinstance(geom_wgs84, (Point, MultiPoint)):
            return MeasurementResult(
                kind=None,
                value_si=None,
                units={},
                perimeter=None,
                measurement_crs="EPSG:4326",
                method="point-zero-dimensional",
                geodesic_value=None,
                delta_percent=None,
                warnings=[],
                status="OK",
            )

        # 4. Repair invalid geometries
        if not geom_wgs84.is_valid:
            geom_wgs84 = shapely.make_valid(geom_wgs84)
            warnings.append("geometry repaired")

        # 5. Determine adaptive projected CRS
        target_crs, method_name = select_measurement_crs(geom_wgs84)
        crs_str = target_crs.to_string()

        # Project geometry to planar meters
        geom_proj = project_geometry(geom_wgs84, target_crs)

        # 6. Polygons and MultiPolygons -> Area & Perimeter
        if isinstance(geom_wgs84, (Polygon, MultiPolygon)):
            planar_area = float(shapely.area(geom_proj))
            planar_perim = float(shapely.length(geom_proj))

            # Geodesic cross-check with hole subtraction guarantee
            geodesic_area, _ = _calculate_geodesic_area_perimeter(geom_wgs84)
            delta = _compute_delta(planar_area, geodesic_area)

            if delta > 0.5:
                warnings.append(f"delta_percent {delta:.2f}% exceeds 0.5% threshold")

            return MeasurementResult(
                kind="area",
                value_si=round(planar_area, 4),
                units=_convert_area_units(planar_area),
                perimeter=round(planar_perim, 4),
                measurement_crs=crs_str,
                method=method_name,
                geodesic_value=round(geodesic_area, 4),
                delta_percent=delta,
                warnings=warnings,
                status="OK",
            )

        # 7. LineString / MultiLineString / LinearRing -> Length
        if isinstance(geom_wgs84, (LineString, MultiLineString, LinearRing)):
            planar_length = float(shapely.length(geom_proj))
            geodesic_length = abs(WGS84_GEOD.geometry_length(geom_wgs84))
            delta = _compute_delta(planar_length, geodesic_length)

            if delta > 0.5:
                warnings.append(f"delta_percent {delta:.2f}% exceeds 0.5% threshold")

            return MeasurementResult(
                kind="length",
                value_si=round(planar_length, 4),
                units=_convert_length_units(planar_length),
                perimeter=None,
                measurement_crs=crs_str,
                method=method_name,
                geodesic_value=round(geodesic_length, 4),
                delta_percent=delta,
                warnings=warnings,
                status="OK",
            )

        # 8. GeometryCollection: Aggregate supported members
        if isinstance(geom_wgs84, GeometryCollection):
            polys = _extract_polygons(geom_wgs84)
            lines = _extract_lines(geom_wgs84)

            has_points = any(isinstance(p, (Point, MultiPoint)) for p in geom_wgs84.geoms)
            if has_points:
                warnings.append("Point member in GeometryCollection ignored for measurement.")

            if polys:
                poly_union = shapely.unary_union(polys)
                poly_proj = project_geometry(poly_union, target_crs)
                planar_area = float(shapely.area(poly_proj))
                planar_perim = float(shapely.length(poly_proj))

                if isinstance(poly_union, (Polygon, MultiPolygon)):
                    geodesic_area, _ = _calculate_geodesic_area_perimeter(poly_union)
                else:
                    geodesic_area = 0.0

                delta = _compute_delta(planar_area, geodesic_area)

                if delta > 0.5:
                    warnings.append(f"delta_percent {delta:.2f}% exceeds 0.5% threshold")

                return MeasurementResult(
                    kind="area",
                    value_si=round(planar_area, 4),
                    units=_convert_area_units(planar_area),
                    perimeter=round(planar_perim, 4),
                    measurement_crs=crs_str,
                    method=method_name,
                    geodesic_value=round(geodesic_area, 4),
                    delta_percent=delta,
                    warnings=warnings,
                    status="OK",
                )

            if lines:
                line_union = shapely.unary_union(lines)
                line_proj = project_geometry(line_union, target_crs)
                planar_length = float(shapely.length(line_proj))
                geodesic_length = abs(WGS84_GEOD.geometry_length(line_union))
                delta = _compute_delta(planar_length, geodesic_length)

                if delta > 0.5:
                    warnings.append(f"delta_percent {delta:.2f}% exceeds 0.5% threshold")

                return MeasurementResult(
                    kind="length",
                    value_si=round(planar_length, 4),
                    units=_convert_length_units(planar_length),
                    perimeter=None,
                    measurement_crs=crs_str,
                    method=method_name,
                    geodesic_value=round(geodesic_length, 4),
                    delta_percent=delta,
                    warnings=warnings,
                    status="OK",
                )

        # 9. Unsupported geometry type
        return MeasurementResult(
            kind=None,
            value_si=None,
            units={},
            perimeter=None,
            measurement_crs="None",
            method="unsupported",
            geodesic_value=None,
            delta_percent=None,
            warnings=[f"Unsupported geometry type '{geom.geom_type}'."],
            status="SKIPPED",
        )

    except Exception as exc:
        # 10. Robustness guarantee: unexpected error on single feature never crashes batch
        return MeasurementResult(
            kind=None,
            value_si=None,
            units={},
            perimeter=None,
            measurement_crs="ERROR",
            method="ERROR",
            geodesic_value=None,
            delta_percent=None,
            warnings=[f"Measurement processing error: {exc}"],
            status="ERROR",
        )
