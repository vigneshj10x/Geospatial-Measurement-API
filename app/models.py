"""SQLAlchemy 2.x models for uploaded files and spatial feature records."""

import uuid
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import JSON, DateTime, Float, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db import Base


class UploadedFile(Base):
    """Represents an uploaded geospatial dataset and its processing lifecycle."""

    __tablename__ = "uploaded_files"

    id: Mapped[str] = mapped_column(
        String(36),
        primary_key=True,
        default=lambda: str(uuid.uuid4()),
    )
    filename: Mapped[str] = mapped_column(String(255), nullable=False)
    file_type: Mapped[str] = mapped_column(String(50), nullable=False)
    status: Mapped[str] = mapped_column(
        String(50),
        nullable=False,
        default="PENDING",
        index=True,
    )  # 'PENDING', 'PROCESSING', 'COMPLETED', 'PARTIAL', 'FAILED'
    crs: Mapped[str | None] = mapped_column(String(100), nullable=True)
    feature_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    warnings: Mapped[list[str]] = mapped_column(JSON, default=list, nullable=False)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    size_bytes: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    storage_path: Mapped[str | None] = mapped_column(String(512), nullable=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(UTC),
        nullable=False,
    )
    processed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )
    processing_duration_ms: Mapped[float | None] = mapped_column(
        Float,
        nullable=True,
    )

    # Cascade delete child feature records when uploaded file is deleted
    features: Mapped[list["FeatureRecord"]] = relationship(
        "FeatureRecord",
        back_populates="uploaded_file",
        cascade="all, delete-orphan",
        order_by="FeatureRecord.idx",
    )


class FeatureRecord(Base):
    """Stores individual geometry feature data, properties, and computed measurements."""

    __tablename__ = "feature_records"

    id: Mapped[str] = mapped_column(
        String(36),
        primary_key=True,
        default=lambda: str(uuid.uuid4()),
    )
    file_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("uploaded_files.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    idx: Mapped[int] = mapped_column(Integer, nullable=False)
    source_layer: Mapped[str] = mapped_column(String(100), nullable=False, default="default")
    geometry_type: Mapped[str] = mapped_column(String(50), nullable=False)

    # GeoJSON representation in ORIGINAL CRS
    geometry: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    properties: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict, nullable=False)

    status: Mapped[str] = mapped_column(
        String(50),
        nullable=False,
        default="OK",
        index=True,
    )  # 'OK', 'SKIPPED', 'ERROR'
    warnings: Mapped[list[str]] = mapped_column(JSON, default=list, nullable=False)
    measurement: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)

    uploaded_file: Mapped["UploadedFile"] = relationship(
        "UploadedFile",
        back_populates="features",
    )


# Backward compatibility alias
FileRecord = UploadedFile
