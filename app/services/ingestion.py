"""File upload ingestion, content-type detection, and security-hardened archive extraction."""

import os
import uuid
import zipfile
from pathlib import Path
from typing import BinaryIO

from fastapi import UploadFile

from app.config import settings
from app.exceptions import (
    FileTooLargeError,
    InvalidGeoFileError,
    UnsupportedFileTypeError,
)

ZIP_MAGIC_SIGNATURES = (
    b"PK\x03\x04",
    b"PK\x05\x06",
    b"PK\x07\x08",
)

CHUNK_SIZE = 64 * 1024  # 64 KB streaming buffer


def detect_file_type_and_validate(file_path: Path) -> str:
    """
    Detect and validate file type by checking both file extension AND binary content.

    Supported formats:
    - 'shapefile_zip': extension .zip with valid zip magic header
    - 'kml': extension .kml with XML content containing KML tags

    Raises UnsupportedFileTypeError (415) if either extension or content is invalid.
    """
    ext = file_path.suffix.lower()

    if ext not in settings.ALLOWED_EXTENSIONS:
        raise UnsupportedFileTypeError(
            f"Unsupported file extension '{ext}'. Only .zip and .kml files are supported.",
            details={"allowed_extensions": list(settings.ALLOWED_EXTENSIONS)},
        )

    # Validate binary content against extension
    with open(file_path, "rb") as f:
        header = f.read(4096)

    if ext == ".zip":
        if not any(header.startswith(sig) for sig in ZIP_MAGIC_SIGNATURES):
            raise UnsupportedFileTypeError(
                "File has .zip extension but does not contain a valid ZIP header signature.",
            )
        if not zipfile.is_zipfile(file_path):
            raise UnsupportedFileTypeError(
                "Uploaded archive failed zip integrity validation.",
            )
        return "shapefile_zip"

    if ext == ".kml":
        try:
            # Check for XML / KML indicators
            header_text = header.decode("utf-8", errors="ignore").lower()
            if not (
                "<kml" in header_text or "<placemark" in header_text or "<document" in header_text
            ):
                raise UnsupportedFileTypeError(
                    "File has .kml extension but does not contain valid KML markup.",
                )
        except Exception as exc:
            raise UnsupportedFileTypeError(
                f"Failed to inspect KML content: {exc}",
            ) from exc
        return "kml"

    raise UnsupportedFileTypeError(f"Unsupported file type: {ext}")


def save_upload_to_storage(
    upload_file: UploadFile | BinaryIO,
    filename: str,
    custom_storage_dir: Path | None = None,
) -> tuple[str, Path]:
    """
    Save uploaded file to a unique per-file directory under the storage path.

    Enforces MAX_UPLOAD_SIZE_BYTES (default 50 MB) streaming check -> error 413.
    Returns (file_uuid, saved_file_path).
    """
    file_id = str(uuid.uuid4())
    base_storage = custom_storage_dir or settings.UPLOAD_DIR
    target_dir = base_storage / file_id
    target_dir.mkdir(parents=True, exist_ok=True)

    dest_path = target_dir / Path(filename).name
    total_bytes = 0

    with open(dest_path, "wb") as buffer:
        if isinstance(upload_file, UploadFile):
            # Stream UploadFile in chunks
            while chunk := upload_file.file.read(CHUNK_SIZE):
                total_bytes += len(chunk)
                if total_bytes > settings.MAX_UPLOAD_SIZE_BYTES:
                    buffer.close()
                    dest_path.unlink(missing_ok=True)
                    raise FileTooLargeError(
                        f"Uploaded file exceeds maximum allowed size of "
                        f"{settings.MAX_UPLOAD_SIZE_BYTES / (1024 * 1024):.1f} MB.",
                        details={
                            "received_bytes": total_bytes,
                            "limit_bytes": settings.MAX_UPLOAD_SIZE_BYTES,
                        },
                    )
                buffer.write(chunk)
        else:
            # Stream raw BinaryIO in chunks
            while chunk := upload_file.read(CHUNK_SIZE):
                total_bytes += len(chunk)
                if total_bytes > settings.MAX_UPLOAD_SIZE_BYTES:
                    buffer.close()
                    dest_path.unlink(missing_ok=True)
                    raise FileTooLargeError(
                        f"Uploaded file exceeds maximum allowed size of "
                        f"{settings.MAX_UPLOAD_SIZE_BYTES / (1024 * 1024):.1f} MB.",
                        details={
                            "received_bytes": total_bytes,
                            "limit_bytes": settings.MAX_UPLOAD_SIZE_BYTES,
                        },
                    )
                buffer.write(chunk)

    return file_id, dest_path


def safe_extract_zip(zip_path: Path, extract_dir: Path) -> list[Path]:
    """
    Extract a ZIP archive safely with defenses against:
    - Zip-slip (directory traversal via relative '..' or absolute paths)
    - Symlinks (arbitrary file read / write)
    - Zip-bombs (limits on uncompressed byte size and file count)
    - macOS metadata artifacts (__MACOSX and hidden files ignored)

    Validates that .shp files have matching .shx and .dbf companion files (case-insensitive).
    Returns list of discovered .shp paths for all valid shapefile layers.
    """
    if not zipfile.is_zipfile(zip_path):
        raise InvalidGeoFileError("Uploaded file is not a valid ZIP archive.")

    extract_dir.mkdir(parents=True, exist_ok=True)
    resolved_extract_dir = extract_dir.resolve()

    with zipfile.ZipFile(zip_path, "r") as archive:
        infolist = archive.infolist()

        # 1. Zip bomb file count limit
        if len(infolist) > settings.MAX_ZIP_FILES:
            raise InvalidGeoFileError(
                f"Archive contains {len(infolist)} files, "
                f"exceeding limit of {settings.MAX_ZIP_FILES}.",
                details={"file_count": len(infolist), "limit": settings.MAX_ZIP_FILES},
            )

        total_uncompressed = 0

        # Filter and validate entries
        entries_to_extract: list[zipfile.ZipInfo] = []

        for info in infolist:
            filename = info.filename
            parts = Path(filename).parts

            # 2. Block absolute paths and directory traversal (Zip-Slip)
            if os.path.isabs(filename) or filename.startswith(("/", "\\")):
                raise InvalidGeoFileError(
                    f"Malicious absolute path detected in zip archive: '{filename}'."
                )
            if ".." in parts:
                raise InvalidGeoFileError(
                    f"Zip-slip path traversal attempt detected in zip archive: '{filename}'."
                )

            # Ignore macOS metadata folders and hidden dotfiles
            if any(p == "__MACOSX" or (p.startswith(".") and p not in (".", "..")) for p in parts):
                continue

            # 3. Detect and block symlinks
            # In Unix zip archives, file mode 0o120000 denotes a symbolic link
            unix_mode = info.external_attr >> 16
            if unix_mode & 0o170000 == 0o120000:
                raise InvalidGeoFileError(
                    f"Symbolic link detected in zip archive: '{filename}'. Symlinks are prohibited."
                )

            if info.is_dir():
                continue

            # 4. Total uncompressed size limit
            total_uncompressed += info.file_size
            if total_uncompressed > settings.MAX_UNCOMPRESSED_SIZE_BYTES:
                raise FileTooLargeError(
                    f"Uncompressed archive exceeds maximum allowed size of "
                    f"{settings.MAX_UNCOMPRESSED_SIZE_BYTES / (1024 * 1024):.1f} MB.",
                    details={
                        "uncompressed_bytes": total_uncompressed,
                        "limit_bytes": settings.MAX_UNCOMPRESSED_SIZE_BYTES,
                    },
                )

            entries_to_extract.append(info)

        # 5. Extract safe entries
        for entry in entries_to_extract:
            target_file = (extract_dir / entry.filename).resolve()
            # Double-check that destination path is strictly within extract_dir
            if not str(target_file).startswith(str(resolved_extract_dir)):
                raise InvalidGeoFileError(f"Zip-slip path escape detected: '{entry.filename}'.")
            target_file.parent.mkdir(parents=True, exist_ok=True)
            with archive.open(entry) as src, open(target_file, "wb") as dst:
                dst.write(src.read())

    # 6. Locate all .shp files (case-insensitive) across all folders
    shp_files: list[Path] = []
    for root, _, files in os.walk(extract_dir):
        for f in files:
            if f.lower().endswith(".shp"):
                shp_files.append(Path(root) / f)

    if not shp_files:
        raise InvalidGeoFileError("No .shp file found inside the ZIP archive.")

    # 7. For each .shp, validate that companion .shx and .dbf files exist (case-insensitive)
    for shp_path in shp_files:
        parent_dir = shp_path.parent
        stem = shp_path.stem.lower()

        # Gather all file stems and extensions in this directory (lowercase)
        files_in_dir = os.listdir(parent_dir)
        extensions_map: dict[str, str] = {}
        for entry_name in files_in_dir:
            p = Path(entry_name)
            if p.stem.lower() == stem:
                extensions_map[p.suffix.lower()] = entry_name

        if ".shx" not in extensions_map:
            raise InvalidGeoFileError(
                f"Missing required shapefile component: '{shp_path.stem}.shx' "
                f"for '{shp_path.name}'.",
                details={"shapefile": shp_path.name, "missing": f"{shp_path.stem}.shx"},
            )
        if ".dbf" not in extensions_map:
            raise InvalidGeoFileError(
                f"Missing required shapefile component: '{shp_path.stem}.dbf' "
                f"for '{shp_path.name}'.",
                details={"shapefile": shp_path.name, "missing": f"{shp_path.stem}.dbf"},
            )

    return shp_files
