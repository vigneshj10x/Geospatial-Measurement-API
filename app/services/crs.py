"""CRS handling, caching, adaptive UTM selection, and equal-area projection fallbacks."""

import functools
from typing import Any

import pyproj
from shapely import ops
from shapely.geometry.base import BaseGeometry

from app.exceptions import InvalidGeoFileError

WGS84_EPSG = "EPSG:4326"


@functools.lru_cache(maxsize=128)
def get_transformer(source_crs_str: str, target_crs_str: str) -> pyproj.Transformer:
    """
    Cached pyproj Transformer lookup.

    Always enforces always_xy=True to guarantee (lon, lat) / (x, y) coordinate ordering.
    """
    src = pyproj.CRS.from_user_input(source_crs_str)
    tgt = pyproj.CRS.from_user_input(target_crs_str)
    return pyproj.Transformer.from_crs(src, tgt, always_xy=True)


def normalize_crs_str(crs_input: Any) -> str:
    """Normalize user/source CRS input into a stable string representation."""
    if crs_input is None:
        return WGS84_EPSG
    if isinstance(crs_input, pyproj.CRS):
        epsg = crs_input.to_epsg()
        return f"EPSG:{epsg}" if epsg else crs_input.to_string()
    try:
        parsed = pyproj.CRS.from_user_input(crs_input)
        epsg = parsed.to_epsg()
        return f"EPSG:{epsg}" if epsg else parsed.to_string()
    except Exception as exc:
        raise InvalidGeoFileError(
            f"Invalid or unrecognized CRS specification: {crs_input}",
            details={"crs": str(crs_input), "error": str(exc)},
        ) from exc


def to_wgs84(geom: BaseGeometry, source_crs_input: Any = None) -> BaseGeometry:
    """
    Ensure geometry coordinates are in WGS84 (EPSG:4326) prior to centroid/zone analysis.

    Uses cached Transformer with always_xy=True.
    """
    if geom.is_empty:
        return geom

    source_crs_str = normalize_crs_str(source_crs_input)
    if source_crs_str.upper() in ("EPSG:4326", "WGS84", "4326"):
        return geom

    transformer = get_transformer(source_crs_str, WGS84_EPSG)
    return ops.transform(transformer.transform, geom)


def compute_utm_zone_and_epsg(lon: float, lat: float) -> tuple[int, int]:
    """
    Compute standard UTM zone (1-60) and 5-digit EPSG code for a given WGS84 coordinate.

    Note on Regional Exceptions (Norway/Svalbard):
    - Southwestern Norway (between 56°N and 64°N): UTM zone 32V is widened to 9°
      (covering 3°E to 12°E) and 31V is narrowed.
    - Svalbard (between 72°N and 84°N): Zones 32X and 34X are not used; zones
      31X, 33X, 35X, and 37X are widened to 9° and 12°.
    For automated algorithmic calculation, standard 6° longitude indexing is applied,
    which provides mathematically sound conformal local projection across all latitudes.
    """
    # Normalize longitude into [-180, 180)
    lon_norm = ((lon + 180.0) % 360.0) - 180.0
    zone = int((lon_norm + 180.0) / 6.0) + 1
    zone = max(1, min(60, zone))

    # EPSG:326xx for North, EPSG:327xx for South
    epsg_code = (32600 if lat >= 0 else 32700) + zone
    return zone, epsg_code


def select_measurement_crs(geom_wgs84: BaseGeometry) -> tuple[pyproj.CRS, str]:
    """
    Determine the optimal projected CRS for metric measurements of a geometry.

    Strategy:
    1. Polar edge cases: Latitudes > 84°N or < -80°S where UTM is undefined
       fall back to EPSG:6933 (World Cylindrical Equal Area).
    2. Multi-zone features: If the geometry bounds cross UTM zone boundaries
       or exceed 6° longitude span, select custom Lambert Azimuthal Equal-Area
       (LAEA) centered on the geometry's centroid (+proj=laea +lat_0=.. +lon_0=..).
    3. Single-zone features: Select the local UTM projection (EPSG:326xx or EPSG:327xx).

    Returns:
        (target_crs, strategy_name) e.g. (CRS, 'UTM-32631') or (CRS, 'LAEA-local')
    """
    if geom_wgs84.is_empty:
        crs = pyproj.CRS.from_epsg(3857)
        return crs, "DEFAULT-3857"

    min_lon, min_lat, max_lon, max_lat = geom_wgs84.bounds
    centroid = geom_wgs84.centroid
    c_lon, c_lat = centroid.x, centroid.y

    # 1. Polar edge cases
    if min_lat < -80.0 or max_lat > 84.0 or c_lat < -80.0 or c_lat > 84.0:
        crs = pyproj.CRS.from_epsg(6933)
        return crs, "EQUAL_AREA-6933"

    # 2. Check if bounds span across UTM zones or exceed ~6 degrees
    lon_span = abs(max_lon - min_lon)
    z_min = int((((min_lon + 180.0) % 360.0) - 180.0 + 180.0) / 6.0) + 1
    z_max = int((((max_lon + 180.0) % 360.0) - 180.0 + 180.0) / 6.0) + 1

    if z_min != z_max or lon_span > 6.0:
        # Multi-zone fallback: Custom Lambert Azimuthal Equal-Area (LAEA)
        laea_proj_str = (
            f"+proj=laea +lat_0={c_lat:.6f} +lon_0={c_lon:.6f} +datum=WGS84 +units=m +no_defs"
        )
        crs = pyproj.CRS.from_user_input(laea_proj_str)
        return crs, "LAEA-local"

    # 3. Single UTM zone
    zone, epsg_code = compute_utm_zone_and_epsg(c_lon, c_lat)
    crs = pyproj.CRS.from_epsg(epsg_code)
    return crs, f"UTM-{epsg_code}"


def project_geometry(
    geom_wgs84: BaseGeometry,
    target_crs: pyproj.CRS,
) -> BaseGeometry:
    """Reproject a WGS84 geometry to a target projected CRS using cached transformer."""
    if geom_wgs84.is_empty:
        return geom_wgs84

    target_str = target_crs.to_string()
    transformer = get_transformer(WGS84_EPSG, target_str)
    return ops.transform(transformer.transform, geom_wgs84)
