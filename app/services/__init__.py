"""Business logic, ingestion, and unified geospatial reading services."""

from app.services.ingestion import (
    detect_file_type_and_validate,
    safe_extract_zip,
    save_upload_to_storage,
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
]
