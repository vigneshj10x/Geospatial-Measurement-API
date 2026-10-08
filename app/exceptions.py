"""Custom domain exceptions mapped to standard HTTP error codes."""

from typing import Any

from fastapi import FastAPI, Request, status
from fastapi.responses import JSONResponse


class AppError(Exception):
    """Base application exception."""

    status_code: int = status.HTTP_500_INTERNAL_SERVER_ERROR
    error_code: str = "INTERNAL_SERVER_ERROR"

    def __init__(
        self,
        message: str,
        *,
        status_code: int | None = None,
        error_code: str | None = None,
        details: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(message)
        self.message = message
        if status_code is not None:
            self.status_code = status_code
        if error_code is not None:
            self.error_code = error_code
        self.details = details or {}


class InvalidGeoFileError(AppError):
    """Raised when an uploaded spatial file is corrupted, incomplete, or invalid."""

    status_code = status.HTTP_400_BAD_REQUEST
    error_code = "INVALID_GEO_FILE"


class FileTooLargeError(AppError):
    """Raised when an uploaded file or uncompressed archive exceeds size limits."""

    status_code = status.HTTP_413_CONTENT_TOO_LARGE
    error_code = "FILE_TOO_LARGE"


class UnsupportedFileTypeError(AppError):
    """Raised when an uploaded file has an unsupported format or invalid magic bytes."""

    status_code = status.HTTP_415_UNSUPPORTED_MEDIA_TYPE
    error_code = "UNSUPPORTED_FILE_TYPE"


def register_exception_handlers(app: FastAPI) -> None:
    """Register uniform JSON error handlers on FastAPI app."""

    @app.exception_handler(AppError)
    async def app_error_handler(_: Request, exc: AppError) -> JSONResponse:
        return JSONResponse(
            status_code=exc.status_code,
            content={
                "error": {
                    "code": exc.error_code,
                    "message": exc.message,
                    "details": exc.details,
                }
            },
        )
