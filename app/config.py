"""Application configuration settings."""

import os
from pathlib import Path

from pydantic import BaseModel, Field


class Settings(BaseModel):
    """Application settings with environment variable fallbacks."""

    PROJECT_NAME: str = "Geospatial File Measurement API"
    VERSION: str = "0.1.0"
    API_V1_STR: str = "/api"

    DATABASE_URL: str = Field(
        default_factory=lambda: os.getenv("DATABASE_URL", "sqlite:///./geospatial.db")
    )
    UPLOAD_DIR: Path = Field(
        default_factory=lambda: Path(os.getenv("UPLOAD_DIR", "./uploads")).resolve()
    )

    # Security & resource guardrails
    MAX_UPLOAD_SIZE_BYTES: int = Field(
        default_factory=lambda: int(
            os.getenv("MAX_UPLOAD_SIZE_BYTES", str(25 * 1024 * 1024))
        )  # 25 MB
    )
    MAX_UNCOMPRESSED_SIZE_BYTES: int = Field(
        default_factory=lambda: int(
            os.getenv("MAX_UNCOMPRESSED_SIZE_BYTES", str(50 * 1024 * 1024))
        )  # 50 MB
    )
    MAX_ZIP_FILES: int = Field(default_factory=lambda: int(os.getenv("MAX_ZIP_FILES", "100")))
    MAX_COMPRESSION_RATIO: float = Field(
        default_factory=lambda: float(os.getenv("MAX_COMPRESSION_RATIO", "100.0"))
    )

    ALLOWED_EXTENSIONS: tuple[str, ...] = (".zip", ".kml")


settings = Settings()
