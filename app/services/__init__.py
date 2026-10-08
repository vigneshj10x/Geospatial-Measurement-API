"""Services package with ingestion, readers, adaptive CRS selection, measurement, and processor."""

from app.services.crs import (
    get_transformer,
    project_geometry,
    select_measurement_crs,
    to_wgs84,
)
from app.services.ingestion import (
    detect_file_type_and_validate,
    safe_extract_zip,
    save_upload_to_storage,
)
from app.services.measurements import (
    MeasurementResult,
    measure_feature,
)
from app.services.processor import (
    process_file,
    sanitize_json_value,
)
from app.services.readers import (
    DatasetReadResult,
    Feature,
    read_kml,
    read_shapefiles,
)

__all__ = [
    "detect_file_type_and_validate",
    "save_upload_to_storage",
    "safe_extract_zip",
    "Feature",
    "DatasetReadResult",
    "read_shapefiles",
    "read_kml",
    "get_transformer",
    "to_wgs84",
    "select_measurement_crs",
    "project_geometry",
    "MeasurementResult",
    "measure_feature",
    "process_file",
    "sanitize_json_value",
]
