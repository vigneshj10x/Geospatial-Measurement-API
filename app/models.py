"""SQLAlchemy 2.x models for file and geospatial feature records."""

import uuid
from datetime import UTC, datetime

from sqlalchemy import DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db import Base


class TimestampMixin:
    """Provides UTC timestamps for created_at and updated_at."""

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(UTC),
        nullable=False,
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(UTC),
        onupdate=lambda: datetime.now(UTC),
        nullable=False,
    )


class FileRecord(Base, TimestampMixin):
    """Represents an uploaded geospatial archive or file and its processing status."""

    __tablename__ = "files"

    id: Mapped[str] = mapped_column(
        String(36),
        primary_key=True,
        default=lambda: str(uuid.uuid4()),
    )
    filename: Mapped[str] = mapped_column(String(255), nullable=False)
    file_format: Mapped[str] = mapped_column(String(50), nullable=False)
    file_size_bytes: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    feature_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    crs: Mapped[str | None] = mapped_column(String(100), nullable=True)
    status: Mapped[str] = mapped_column(
        String(50),
        nullable=False,
        default="pending",
        index=True,
    )
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    storage_path: Mapped[str | None] = mapped_column(String(512), nullable=True)

    features: Mapped[list["FeatureRecord"]] = relationship(
        "FeatureRecord",
        back_populates="file_record",
        cascade="all, delete-orphan",
        order_by="FeatureRecord.feature_index",
    )


class FeatureRecord(Base, TimestampMixin):
    """Stores individual geometry feature data, properties, and computed measurements."""

    __tablename__ = "features"

    id: Mapped[str] = mapped_column(
        String(36),
        primary_key=True,
        default=lambda: str(uuid.uuid4()),
    )
    file_id: Mapped[str] = mapped_column(
        String(36),
        ForeignKey("files.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    feature_index: Mapped[int] = mapped_column(Integer, nullable=False)
    feature_identifier: Mapped[str | None] = mapped_column(String(255), nullable=True)
    geometry_type: Mapped[str] = mapped_column(String(50), nullable=False)

    geometry_geojson: Mapped[str] = mapped_column(Text, nullable=False)
    properties_json: Mapped[str] = mapped_column(Text, nullable=False, default="{}")

    source_crs: Mapped[str | None] = mapped_column(String(100), nullable=True)
    projected_crs: Mapped[str | None] = mapped_column(String(255), nullable=True)
    measurements_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    warnings_json: Mapped[str | None] = mapped_column(Text, nullable=True)

    status: Mapped[str] = mapped_column(
        String(50),
        nullable=False,
        default="measured",
        index=True,
    )

    file_record: Mapped["FileRecord"] = relationship(
        "FileRecord",
        back_populates="features",
    )
