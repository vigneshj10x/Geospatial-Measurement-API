"""Unit tests for the geospatial unit conversion module."""

import pytest

from app.services.units import (
    convert_area_to_unit,
    convert_area_units,
    convert_length_to_unit,
    convert_length_units,
    format_measurement_value,
)


def test_convert_area_units_known_values() -> None:
    """Verify area conversion values from square meters."""
    # 10,000 m2 = 1.0 hectare, approx 2.47105 acres, 0.01 km2
    units = convert_area_units(10000.0)
    assert units["m2"] == 10000.0
    assert pytest.approx(units["hectares"], rel=1e-5) == 1.0
    assert pytest.approx(units["acres"], rel=1e-3) == 2.47105
    assert pytest.approx(units["km2"], rel=1e-5) == 0.01
    assert units["sq_feet"] > 0
    assert units["sq_miles"] > 0


def test_convert_length_units_known_values() -> None:
    """Verify length conversion values from meters."""
    # 1,000 meters = 1.0 km, approx 0.621371 miles, 3280.84 feet
    units = convert_length_units(1000.0)
    assert units["m"] == 1000.0
    assert pytest.approx(units["km"], rel=1e-5) == 1.0
    assert pytest.approx(units["miles"], rel=1e-3) == 0.621371
    assert pytest.approx(units["feet"], rel=1e-2) == 3280.84


def test_convert_to_individual_units() -> None:
    """Test targeted unit conversion helpers with unit alias variations."""
    # Area
    assert pytest.approx(convert_area_to_unit(10000.0, "ha"), rel=1e-5) == 1.0
    assert pytest.approx(convert_area_to_unit(10000.0, "hectares"), rel=1e-5) == 1.0
    assert pytest.approx(convert_area_to_unit(10000.0, "km2"), rel=1e-5) == 0.01
    assert pytest.approx(convert_area_to_unit(10000.0, "m2"), rel=1e-5) == 10000.0

    # Length
    assert pytest.approx(convert_length_to_unit(5000.0, "km"), rel=1e-5) == 5.0
    assert pytest.approx(convert_length_to_unit(5000.0, "m"), rel=1e-5) == 5000.0
    assert pytest.approx(convert_length_to_unit(1609.344, "miles"), rel=1e-4) == 1.0

    # Invalid unit raises ValueError
    with pytest.raises(ValueError, match="Unsupported area unit"):
        convert_area_to_unit(100.0, "unknown_area_unit")

    with pytest.raises(ValueError, match="Unsupported length unit"):
        convert_length_to_unit(100.0, "unknown_length_unit")


def test_format_measurement_value() -> None:
    """Test formatting numbers with units and precision."""
    assert format_measurement_value(12345.678, "m2", precision=2) == "12,345.68 m2"
    assert format_measurement_value(None, "m2") == "N/A"
