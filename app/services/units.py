"""Unit conversion utilities for high-precision geospatial area and length measurements."""

from typing import Any

# Area conversion constants from square meters (m²)
M2_TO_HECTARES = 1e-4
M2_TO_ACRES = 1.0 / 4046.8564224
M2_TO_KM2 = 1e-6
M2_TO_SQ_FEET = 10.763910416709722
M2_TO_SQ_MILES = 1.0 / 2589988.110336

# Length conversion constants from meters (m)
METERS_TO_KM = 1e-3
METERS_TO_MILES = 1.0 / 1609.344
METERS_TO_FEET = 3.280839895013123


def convert_area_units(area_m2: float) -> dict[str, float]:
    """
    Convert square meters into standard area units rounded to clean precision.

    Returns dict containing m2, hectares, acres, km2, square_kilometers, sq_feet, and sq_miles.
    """
    km2_val = round(area_m2 * M2_TO_KM2, 6)
    return {
        "m2": round(area_m2, 4),
        "hectares": round(area_m2 * M2_TO_HECTARES, 6),
        "acres": round(area_m2 * M2_TO_ACRES, 6),
        "km2": km2_val,
        "square_kilometers": km2_val,
        "sq_feet": round(area_m2 * M2_TO_SQ_FEET, 2),
        "sq_miles": round(area_m2 * M2_TO_SQ_MILES, 6),
    }


def convert_length_units(length_m: float) -> dict[str, float]:
    """
    Convert meters into standard distance units rounded to clean precision.

    Returns dict containing m, km, kilometers, miles, and feet.
    """
    km_val = round(length_m * METERS_TO_KM, 6)
    return {
        "m": round(length_m, 4),
        "km": km_val,
        "kilometers": km_val,
        "miles": round(length_m * METERS_TO_MILES, 6),
        "feet": round(length_m * METERS_TO_FEET, 2),
    }


def convert_area_to_unit(area_m2: float, target_unit: str) -> float:
    """Convert an area in square meters to a single specific unit."""
    unit_map = {
        "m2": area_m2,
        "m²": area_m2,
        "sq_meters": area_m2,
        "hectares": area_m2 * M2_TO_HECTARES,
        "ha": area_m2 * M2_TO_HECTARES,
        "acres": area_m2 * M2_TO_ACRES,
        "km2": area_m2 * M2_TO_KM2,
        "km²": area_m2 * M2_TO_KM2,
        "square_kilometers": area_m2 * M2_TO_KM2,
        "sq_feet": area_m2 * M2_TO_SQ_FEET,
        "ft2": area_m2 * M2_TO_SQ_FEET,
        "sq_miles": area_m2 * M2_TO_SQ_MILES,
        "mi2": area_m2 * M2_TO_SQ_MILES,
    }
    unit_key = target_unit.lower().strip()
    if unit_key not in unit_map:
        raise ValueError(
            f"Unsupported area unit '{target_unit}'. Supported: {list(unit_map.keys())}"
        )
    return unit_map[unit_key]


def convert_length_to_unit(length_m: float, target_unit: str) -> float:
    """Convert a length in meters to a single specific unit."""
    unit_map = {
        "m": length_m,
        "meters": length_m,
        "km": length_m * METERS_TO_KM,
        "kilometers": length_m * METERS_TO_KM,
        "miles": length_m * METERS_TO_MILES,
        "mi": length_m * METERS_TO_MILES,
        "feet": length_m * METERS_TO_FEET,
        "ft": length_m * METERS_TO_FEET,
    }
    unit_key = target_unit.lower().strip()
    if unit_key not in unit_map:
        raise ValueError(
            f"Unsupported length unit '{target_unit}'. Supported: {list(unit_map.keys())}"
        )
    return unit_map[unit_key]


def format_measurement_value(val: float | None, unit: str, precision: int = 2) -> str:
    """Format numerical measurement value with unit string."""
    if val is None:
        return "N/A"
    return f"{val:,.{precision}f} {unit}"
