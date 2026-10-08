"""Pydantic v2 schemas for health, file upload, metadata, and spatial measurements."""

from datetime import datetime
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class HealthResponse(BaseModel):
    """Health check response schema."""

    status: str = Field(default="ok", description="Operational health status")
    app: str = Field(default="Geospatial Measurement API", description="Service application name")
    version: str = Field(default="0.1.0", description="Semantic service version")


class ErrorDetail(BaseModel):
    """Standardized error detail payload."""

    code: str = Field(
        ..., description="Machine-readable error classification code", examples=["INVALID_GEO_FILE"]
    )
    message: str = Field(
        ...,
        description="Human-readable error explanation",
        examples=["Missing required .shp component."],
    )
    details: dict[str, Any] = Field(
        default_factory=dict, description="Supplementary debugging context"
    )


class ErrorResponse(BaseModel):
    """Uniform error response envelope."""

    error: ErrorDetail


class FileStatus(StrEnum):
    """Lifecycle status of an uploaded spatial file."""

    PENDING = "PENDING"
    PROCESSING = "PROCESSING"
    COMPLETED = "COMPLETED"
    PARTIAL = "PARTIAL"
    FAILED = "FAILED"


class FileLinks(BaseModel):
    """Hypermedia navigation links for an uploaded file."""

    self: str = Field(..., description="Resource metadata URL", examples=["/api/files/12345/"])
    measurements: str = Field(
        ..., description="Feature measurements URL", examples=["/api/files/12345/measurements/"]
    )


class FileUploadResponse(BaseModel):
    """Response returned upon file upload registration or synchronous processing completion."""

    id: str = Field(
        ..., description="Unique dataset UUID", examples=["3fa85f64-5717-4562-b3fc-2c963f66afa6"]
    )
    filename: str = Field(..., description="Original upload filename", examples=["parcels.zip"])
    status: str = Field(
        ...,
        description="Current processing status (PENDING, PROCESSING, COMPLETED, PARTIAL, FAILED)",
        examples=["COMPLETED"],
    )
    feature_count: int = Field(
        default=0, description="Total extracted spatial features", examples=[42]
    )
    crs: str | None = Field(
        default=None,
        description="Detected source coordinate reference system",
        examples=["EPSG:4326"],
    )
    links: dict[str, str] = Field(..., description="Hypermedia links to self and measurements")
    processing_duration_ms: float | None = Field(
        default=None,
        description="End-to-end processing duration in milliseconds if processed synchronously",
        examples=[45.2],
    )

    model_config = ConfigDict(from_attributes=True)


class FileSummary(BaseModel):
    """Aggregated spatial statistics and quality metrics for an uploaded file."""

    total_area_m2: float = Field(
        default=0.0, description="Total computed polygon area in square meters", examples=[150240.5]
    )
    total_length_m: float = Field(
        default=0.0, description="Total computed line length in meters", examples=[1250.75]
    )
    ok_count: int = Field(
        default=0, description="Count of features successfully measured", examples=[40]
    )
    skipped_count: int = Field(
        default=0, description="Count of features skipped by design (e.g. Points)", examples=[2]
    )
    error_count: int = Field(
        default=0, description="Count of features that raised processing errors", examples=[0]
    )


class FileDetailResponse(BaseModel):
    """Detailed file metadata and processing summary response."""

    id: str = Field(
        ..., description="Unique dataset UUID", examples=["3fa85f64-5717-4562-b3fc-2c963f66afa6"]
    )
    filename: str = Field(..., description="Original upload filename", examples=["districts.kml"])
    feature_count: int = Field(..., description="Total extracted spatial features", examples=[15])
    crs: str | None = Field(
        default=None, description="Detected coordinate reference system", examples=["EPSG:4326"]
    )
    status: str = Field(..., description="Processing status", examples=["COMPLETED"])
    file_type: str = Field(..., description="Detected file type", examples=["kml"])
    warnings: list[str] = Field(
        default_factory=list, description="Dataset-level warnings during ingestion or projection"
    )
    error: str | None = Field(
        default=None, description="Error message if status is FAILED or PARTIAL"
    )
    created_at: datetime = Field(..., description="Timestamp when upload was received")
    processed_at: datetime | None = Field(
        default=None, description="Timestamp when processing concluded"
    )
    processing_duration_ms: float | None = Field(
        default=None,
        description="Total end-to-end processing duration in milliseconds",
        examples=[45.2],
    )
    geometry_type_counts: dict[str, int] = Field(
        default_factory=dict,
        description="Histogram of geometry types encountered",
        examples=[{"Polygon": 12, "Point": 3}],
    )
    summary: FileSummary = Field(..., description="Aggregated measurement summary")

    model_config = ConfigDict(from_attributes=True)


class FileListItemResponse(BaseModel):
    """Item summary in paginated dataset list."""

    id: str = Field(..., description="Unique dataset UUID")
    filename: str = Field(..., description="Original upload filename")
    file_type: str = Field(..., description="Detected file type")
    status: str = Field(..., description="Processing status")
    feature_count: int = Field(..., description="Extracted feature count")
    crs: str | None = Field(default=None, description="Coordinate reference system")
    size_bytes: int = Field(..., description="Original upload size in bytes")
    created_at: datetime = Field(..., description="Upload timestamp")
    processed_at: datetime | None = Field(default=None, description="Processing timestamp")
    processing_duration_ms: float | None = Field(
        default=None,
        description="Total end-to-end processing duration in milliseconds",
        examples=[45.2],
    )
    links: dict[str, str] = Field(..., description="Navigation links")

    model_config = ConfigDict(from_attributes=True)


class FileListResponse(BaseModel):
    """Paginated list of uploaded files."""

    total: int = Field(
        ..., description="Total number of uploaded files matching criteria", examples=[1]
    )
    limit: int = Field(..., description="Page limit", examples=[100])
    offset: int = Field(..., description="Page offset", examples=[0])
    items: list[FileListItemResponse] = Field(..., description="Page items")


class MeasurementDetail(BaseModel):
    """Computed metric payload for a single feature."""

    kind: str | None = Field(
        default=None, description="Measurement kind ('area' or 'length')", examples=["area"]
    )
    value: float | None = Field(
        default=None,
        description="Primary SI metric value (m2 for area, m for length)",
        examples=[15000.0],
    )
    unit: str | None = Field(
        default=None, description="Primary SI unit ('m2' or 'm')", examples=["m2"]
    )
    all_units: dict[str, float] = Field(
        default_factory=dict,
        description="Alternative unit representations",
        examples=[{"m2": 15000.0, "hectares": 1.5, "acres": 3.70658, "km2": 0.015}],
    )
    perimeter: float | None = Field(
        default=None,
        description="Polygon boundary perimeter in meters (if applicable)",
        examples=[500.0],
    )
    measurement_crs: str | None = Field(
        default=None,
        description="Projected planar CRS used for calculations",
        examples=["EPSG:32618"],
    )
    method: str | None = Field(
        default=None,
        description="Projection strategy utilized",
        examples=["UTM Zone 18N (EPSG:32618)"],
    )
    geodesic_value: float | None = Field(
        default=None, description="Pyproj geodesic cross-check value", examples=[15002.3]
    )
    delta_percent: float | None = Field(
        default=None,
        description="Percentage discrepancy between planar and geodesic values",
        examples=[0.015],
    )


class FeatureMeasurementItem(BaseModel):
    """Measurement and geometry payload for an individual spatial feature."""

    index: int = Field(
        ..., description="Zero-based feature index within the source file", examples=[0]
    )
    geometry_type: str = Field(..., description="Shapely geometry type", examples=["Polygon"])
    geometry: dict[str, Any] | None = Field(
        default=None, description="GeoJSON geometry dictionary in ORIGINAL CRS"
    )
    crs: str | None = Field(
        default=None,
        description="Original source coordinate reference system",
        examples=["EPSG:4326"],
    )
    properties: dict[str, Any] = Field(
        default_factory=dict, description="Sanitized feature attribute properties"
    )
    status: str = Field(
        ..., description="Individual feature status: OK, SKIPPED, ERROR", examples=["OK"]
    )
    warnings: list[str] = Field(default_factory=list, description="Per-feature processing warnings")
    measurement: MeasurementDetail | None = Field(
        default=None, description="Computed measurement details"
    )


class PaginatedMeasurementsResponse(BaseModel):
    """Paginated collection of feature measurements in standard JSON format."""

    total: int = Field(
        ..., description="Total feature count matching query filters", examples=[100]
    )
    limit: int = Field(..., description="Pagination limit", examples=[100])
    offset: int = Field(..., description="Pagination offset", examples=[0])
    items: list[FeatureMeasurementItem] = Field(..., description="Measured feature records")


class GeoJSONFeature(BaseModel):
    """GeoJSON Feature representation containing measurement attributes."""

    type: str = Field(default="Feature", description="GeoJSON element type")
    id: str | None = Field(default=None, description="Feature record UUID")
    geometry: dict[str, Any] | None = Field(
        default=None, description="GeoJSON geometry object in original CRS"
    )
    properties: dict[str, Any] = Field(
        default_factory=dict, description="Feature attributes including embedded measurement"
    )


class GeoJSONFeatureCollection(BaseModel):
    """GeoJSON FeatureCollection enclosing measured features."""

    type: str = Field(default="FeatureCollection", description="GeoJSON collection type")
    total: int = Field(..., description="Total matching features count", examples=[100])
    limit: int = Field(..., description="Page limit", examples=[100])
    offset: int = Field(..., description="Page offset", examples=[0])
    features: list[GeoJSONFeature] = Field(..., description="GeoJSON features")
