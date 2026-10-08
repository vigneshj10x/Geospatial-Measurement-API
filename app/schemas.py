"""Pydantic v2 schemas for health, file upload, and measurements."""

from datetime import datetime
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class HealthResponse(BaseModel):
    """Health check response schema."""

    status: str = "ok"
    app: str = "Geospatial Measurement API"
    version: str = "0.1.0"


class ErrorDetail(BaseModel):
    """Standardized error detail payload."""

    code: str
    message: str
    details: dict[str, Any] = Field(default_factory=dict)


class ErrorResponse(BaseModel):
    """Standardized error envelope."""

    error: ErrorDetail


class FileStatus(StrEnum):
    """Lifecycle status of an uploaded spatial file."""

    PENDING = "pending"
    PROCESSING = "processing"
    COMPLETED = "completed"
    FAILED = "failed"


class FileUploadResponse(BaseModel):
    """Response returned upon successful file upload registration."""

    id: str
    filename: str
    file_format: str
    file_size_bytes: int
    status: FileStatus
    message: str = "File uploaded and scheduled for measurement processing."

    model_config = ConfigDict(from_attributes=True)


class FileDetailResponse(BaseModel):
    """Metadata response for GET /api/files/{id}/."""

    id: str
    filename: str
    file_format: str
    file_size_bytes: int
    feature_count: int
    crs: str | None = None
    status: FileStatus
    error_message: str | None = None
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)
