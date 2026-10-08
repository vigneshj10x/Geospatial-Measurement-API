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


class NotFoundError(AppError):
    """Raised when a requested resource or file ID is not found."""

    status_code = status.HTTP_404_NOT_FOUND
    error_code = "NOT_FOUND"


class ConflictError(AppError):
    """Raised when a resource state conflicts with the operation (e.g. still processing)."""

    status_code = status.HTTP_409_CONFLICT
    error_code = "CONFLICT"


def register_exception_handlers(app: FastAPI) -> None:
    """Register uniform JSON error handlers: {"error": {"code": "...", "message": "..."}}."""
    from fastapi.exceptions import RequestValidationError
    from starlette.exceptions import HTTPException as StarletteHTTPException

    @app.exception_handler(AppError)
    async def app_error_handler(_: Request, exc: AppError) -> JSONResponse:
        error_body: dict[str, Any] = {
            "code": exc.error_code,
            "message": exc.message,
        }
        if exc.details:
            error_body["details"] = exc.details
        return JSONResponse(
            status_code=exc.status_code,
            content={"error": error_body},
        )

    @app.exception_handler(StarletteHTTPException)
    async def http_exception_handler(_: Request, exc: StarletteHTTPException) -> JSONResponse:
        code_map = {
            400: "BAD_REQUEST",
            404: "NOT_FOUND",
            405: "METHOD_NOT_ALLOWED",
            409: "CONFLICT",
            413: "FILE_TOO_LARGE",
            415: "UNSUPPORTED_MEDIA_TYPE",
            422: "VALIDATION_ERROR",
            500: "INTERNAL_SERVER_ERROR",
        }
        code = code_map.get(exc.status_code, f"HTTP_{exc.status_code}")
        msg = exc.detail if isinstance(exc.detail, str) else str(exc.detail)
        return JSONResponse(
            status_code=exc.status_code,
            content={"error": {"code": code, "message": msg}},
        )

    @app.exception_handler(RequestValidationError)
    async def validation_exception_handler(_: Request, exc: RequestValidationError) -> JSONResponse:
        errors = exc.errors()
        messages = []
        for err in errors:
            loc = " -> ".join(str(item) for item in err.get("loc", []))
            messages.append(f"{loc}: {err.get('msg', 'invalid value')}")
        clean_msg = "; ".join(messages) if messages else "Request validation failed."
        return JSONResponse(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            content={
                "error": {
                    "code": "VALIDATION_ERROR",
                    "message": clean_msg,
                    "details": {"validation_errors": errors},
                }
            },
        )
