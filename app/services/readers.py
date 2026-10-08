"""Unified geospatial readers for Shapefiles and KML files with Z-coordinate stripping."""

import math
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import defusedxml.ElementTree as ET
import pandas as pd
import pyogrio
import shapely
from shapely.geometry import (
    GeometryCollection,
    LineString,
    MultiLineString,
    MultiPoint,
    MultiPolygon,
    Point,
    Polygon,
)
from shapely.geometry.base import BaseGeometry

from app.exceptions import InvalidGeoFileError


@dataclass
class Feature:
    """Unified internal representation of an extracted geospatial feature."""

    index: int
    geometry: BaseGeometry | None
    measurement_geometry: BaseGeometry | None
    properties: dict[str, Any]
    source_layer: str
    status: str = "VALID"
    warnings: list[str] = field(default_factory=list)


@dataclass
class DatasetReadResult:
    """Container for features, detected CRS, and dataset-level diagnostic warnings."""

    features: list[Feature]
    crs: str
    file_warnings: list[str] = field(default_factory=list)


def _sanitize_property_value(val: Any) -> Any:
    """Normalize NumPy, Pandas, Timestamp, and NaN values into standard Python primitives."""
    if val is None:
        return None
    if isinstance(val, (float, int)):
        if isinstance(val, float) and (math.isnan(val) or math.isinf(val)):
            return None
        return val
    if isinstance(val, (pd.Timestamp,)):
        return val.isoformat()
    if hasattr(val, "item"):
        scalar = val.item()
        if isinstance(scalar, float) and (math.isnan(scalar) or math.isinf(scalar)):
            return None
        return scalar
    if isinstance(val, (list, tuple)):
        return [_sanitize_property_value(v) for v in val]
    if isinstance(val, dict):
        return {str(k): _sanitize_property_value(v) for k, v in val.items()}
    return str(val) if not isinstance(val, (str, bool)) else val


def _extract_properties(row: pd.Series) -> dict[str, Any]:
    """Extract non-geometry columns from a pandas Series into a clean dictionary."""
    props: dict[str, Any] = {}
    for col_name, val in row.items():
        if str(col_name).lower() in ("geometry", "geom"):
            continue
        props[str(col_name)] = _sanitize_property_value(val)

    # Normalize common KML uppercase attributes for developer convenience
    if "Name" in props and "name" not in props:
        props["name"] = props["Name"]
    if "Description" in props and "description" not in props:
        props["description"] = props["Description"]

    return props


def _parse_coord_triplet(coord_str: str) -> tuple[float, ...]:
    """Parse a single KML coordinate string 'lon,lat[,z]' into a float tuple."""
    parts = [float(p.strip()) for p in coord_str.strip().split(",") if p.strip()]
    return tuple(parts)


def _parse_kml_coordinates(coords_text: str | None) -> list[tuple[float, ...]]:
    """Parse whitespace-separated coordinate triplets from a KML <coordinates> tag."""
    if not coords_text:
        return []
    coords: list[tuple[float, ...]] = []
    for chunk in coords_text.strip().split():
        if chunk.strip():
            coords.append(_parse_coord_triplet(chunk))
    return coords


def _find_elem(
    parent: ET.Element, *queries: str, ns: dict[str, str] | None = None
) -> ET.Element | None:
    """Safely find sub-element avoiding ElementTree boolean truthiness pitfall."""
    for q in queries:
        el = parent.find(q, ns) if ns else parent.find(q)
        if el is not None:
            return el
    return None


def _xml_parse_geometry(elem: ET.Element, ns: dict[str, str]) -> BaseGeometry | None:
    """
    Fallback geometry parser using XML ElementTree for Point, LineString, Polygon, MultiGeometry.
    Note: Serves as a pure-Python fallback when GDAL/pyogrio KML drivers are unavailable.
    """
    tag = elem.tag.split("}")[-1] if "}" in elem.tag else elem.tag

    if tag == "Point":
        coords_el = _find_elem(elem, ".//{*}coordinates", ".//coordinates", ns=ns)
        if coords_el is not None and coords_el.text:
            coords = _parse_kml_coordinates(coords_el.text)
            if coords:
                return Point(coords[0])
        return None

    if tag == "LineString":
        coords_el = _find_elem(elem, ".//{*}coordinates", ".//coordinates", ns=ns)
        if coords_el is not None and coords_el.text:
            coords = _parse_kml_coordinates(coords_el.text)
            if len(coords) >= 2:
                return LineString(coords)
        return None

    if tag == "Polygon":
        outer_el = _find_elem(
            elem,
            ".//{*}outerBoundaryIs//{*}coordinates",
            ".//outerBoundaryIs//coordinates",
            ns=ns,
        )
        if outer_el is not None and outer_el.text:
            exterior_coords = _parse_kml_coordinates(outer_el.text)
            if len(exterior_coords) >= 3:
                inner_coords: list[list[tuple[float, ...]]] = []
                inner_els = elem.findall(".//{*}innerBoundaryIs//{*}coordinates", ns)
                if not inner_els:
                    inner_els = elem.findall(".//innerBoundaryIs//coordinates", ns)
                for inner_el in inner_els:
                    if inner_el.text:
                        hole = _parse_kml_coordinates(inner_el.text)
                        if len(hole) >= 3:
                            inner_coords.append(hole)
                return Polygon(exterior_coords, holes=inner_coords)
        return None

    if tag == "MultiGeometry":
        parts: list[BaseGeometry] = []
        for child in elem:
            child_geom = _xml_parse_geometry(child, ns)
            if child_geom is not None and not child_geom.is_empty:
                parts.append(child_geom)
        if not parts:
            return None
        if all(isinstance(p, Polygon) for p in parts):
            return MultiPolygon(parts)
        if all(isinstance(p, LineString) for p in parts):
            return MultiLineString(parts)
        if all(isinstance(p, Point) for p in parts):
            return MultiPoint(parts)
        return GeometryCollection(parts)

    return None


def read_kml_fallback(kml_path: Path) -> list[Feature]:
    """
    Fallback parser for KML using defusedxml ElementTree when C-level drivers are unavailable.
    Extracts Placemark attributes and Point/LineString/Polygon/MultiGeometry geometries.
    """
    try:
        tree = ET.parse(kml_path)
    except Exception as exc:
        raise InvalidGeoFileError(
            f"Failed to parse KML XML document: {exc}",
            details={"path": str(kml_path), "error": str(exc)},
        ) from exc

    root = tree.getroot()
    features: list[Feature] = []
    feature_idx = 0

    placemarks = root.findall(".//{*}Placemark")
    if not placemarks:
        placemarks = root.findall(".//Placemark")

    for pm in placemarks:
        name_el = _find_elem(pm, "{*}name", "name")
        desc_el = _find_elem(pm, "{*}description", "description")
        props: dict[str, Any] = {}
        if name_el is not None and name_el.text:
            props["name"] = name_el.text.strip()
        if desc_el is not None and desc_el.text:
            props["description"] = desc_el.text.strip()

        geom: BaseGeometry | None = None
        for tag in ("Polygon", "LineString", "Point", "MultiGeometry"):
            g_el = _find_elem(pm, f"{{*}}{tag}", tag)
            if g_el is not None:
                geom = _xml_parse_geometry(g_el, {})
                break

        status = "VALID"
        warnings: list[str] = []
        meas_geom: BaseGeometry | None = None

        if not isinstance(geom, BaseGeometry) or geom.is_empty:
            status = "SKIPPED"
            warnings.append("Empty or null geometry.")
            geom_out = None
        else:
            meas_geom = shapely.force_2d(geom)
            geom_out = geom

        features.append(
            Feature(
                index=feature_idx,
                geometry=geom_out,
                measurement_geometry=meas_geom,
                properties=props,
                source_layer="KML_Placemarks",
                status=status,
                warnings=warnings,
            )
        )
        feature_idx += 1

    return features


def read_shapefiles(shp_paths: list[Path]) -> DatasetReadResult:
    """
    Read one or more Shapefile layers into a unified feature list.

    CRS Handling:
    - Inspects the .prj companion file for each shapefile.
    - If .prj is missing, assumes EPSG:4326 and records a file-level warning.
    - Tags each feature with its source layer name (shp_path.stem).
    - Uses shapely.force_2d to drop Z elevation while retaining the original geometry.
    - Handles null/empty geometries by marking the feature as SKIPPED with a diagnostic warning.
    """
    features: list[Feature] = []
    file_warnings: list[str] = []
    detected_crs: str = "EPSG:4326"
    feature_counter = 0

    for shp_path in shp_paths:
        source_layer_name = shp_path.stem
        parent_dir = shp_path.parent

        # 1. Check for .prj file (case-insensitive)
        prj_found = False
        stem_lower = source_layer_name.lower()
        for f in os.listdir(parent_dir):
            p = Path(f)
            if p.stem.lower() == stem_lower and p.suffix.lower() == ".prj":
                prj_found = True
                break

        if not prj_found:
            warning_msg = "No .prj found; assumed EPSG:4326 (defaulted to EPSG:4326)"
            if warning_msg not in file_warnings:
                file_warnings.append(warning_msg)

        # 2. Read dataset via pyogrio
        try:
            df = pyogrio.read_dataframe(shp_path)
        except Exception as exc:
            raise InvalidGeoFileError(
                f"Failed to read shapefile '{shp_path.name}': {exc}",
                details={"file": shp_path.name, "error": str(exc)},
            ) from exc

        # Update detected CRS
        if prj_found and df.crs is not None:
            detected_crs = df.crs.to_string()
        elif not prj_found:
            detected_crs = "EPSG:4326"

        # 3. Process features
        for _, row in df.iterrows():
            geom = row.geometry
            props = _extract_properties(row)
            warnings: list[str] = []
            status = "VALID"
            meas_geom: BaseGeometry | None = None

            if not isinstance(geom, BaseGeometry) or geom.is_empty:
                status = "SKIPPED"
                warnings.append("Empty or null geometry.")
                geom_out = None
            else:
                meas_geom = shapely.force_2d(geom)
                geom_out = geom

            features.append(
                Feature(
                    index=feature_counter,
                    geometry=geom_out,
                    measurement_geometry=meas_geom,
                    properties=props,
                    source_layer=source_layer_name,
                    status=status,
                    warnings=warnings,
                )
            )
            feature_counter += 1

    return DatasetReadResult(
        features=features,
        crs=detected_crs,
        file_warnings=file_warnings,
    )


def read_kml(kml_path: Path) -> DatasetReadResult:
    """
    Read a KML file into unified feature representations.

    Features:
    - CRS is always EPSG:4326 per the OGC KML standard.
    - Discovers and reads ALL layers/folders using pyogrio.list_layers.
    - Falls back to pure-Python XML parser if the underlying GDAL driver fails.
    - Uses shapely.force_2d for planar measurement copies while preserving original geometry.
    - Preserves empty/null geometries, marking them as SKIPPED.
    """
    features: list[Feature] = []
    file_warnings: list[str] = []
    feature_counter = 0

    try:
        # Check layers available in KML
        raw_layers = pyogrio.list_layers(kml_path)
        layer_names: list[str] = []

        if hasattr(raw_layers, "ndim") and raw_layers.ndim >= 1:
            for row in raw_layers:
                name = row[0] if hasattr(row, "__getitem__") else str(row)
                layer_names.append(str(name))
        elif isinstance(raw_layers, list):
            for item in raw_layers:
                layer_names.append(item[0] if isinstance(item, (list, tuple)) else str(item))
        else:
            layer_names = ["KML_Layer"]

        # Read each layer
        for layer_name in layer_names:
            try:
                df = pyogrio.read_dataframe(kml_path, layer=layer_name)
            except Exception:
                df = pyogrio.read_dataframe(kml_path)

            for _, row in df.iterrows():
                geom = row.geometry
                props = _extract_properties(row)
                warnings: list[str] = []
                status = "VALID"
                meas_geom: BaseGeometry | None = None

                if not isinstance(geom, BaseGeometry) or geom.is_empty:
                    status = "SKIPPED"
                    warnings.append("Empty or null geometry.")
                    geom_out = None
                else:
                    meas_geom = shapely.force_2d(geom)
                    geom_out = geom

                features.append(
                    Feature(
                        index=feature_counter,
                        geometry=geom_out,
                        measurement_geometry=meas_geom,
                        properties=props,
                        source_layer=layer_name,
                        status=status,
                        warnings=warnings,
                    )
                )
                feature_counter += 1

    except Exception:
        # Fallback to XML ElementTree parser for Point, LineString, Polygon, Multi*
        features = read_kml_fallback(kml_path)
        file_warnings.append("Processed via pure-Python XML KML fallback parser.")

    if not features:
        raise InvalidGeoFileError(
            f"KML file '{kml_path.name}' contains no readable placemarks or layers.",
            details={"file": kml_path.name},
        )

    return DatasetReadResult(
        features=features,
        crs="EPSG:4326",
        file_warnings=file_warnings,
    )
