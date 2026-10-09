"""FastAPI application entrypoint, middleware, routers, and OpenAPI documentation."""

import time
import uuid
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from app.api.files import router as files_router
from app.config import settings
from app.db import init_db
from app.exceptions import register_exception_handlers
from app.logger import logger, request_id_ctx_var, setup_logging
from app.schemas import HealthResponse

# Initialize structured logging on application load
setup_logging()

TAGS_METADATA = [
    {
        "name": "Files",
        "description": (
            "Geospatial dataset ingestion (.zip Shapefile, .kml), metadata inspection, "
            "lifecycle status, and deletion."
        ),
    },
    {
        "name": "Measurements",
        "description": (
            "High-precision geometric measurements (polygon area, line length), pagination, "
            "filtering, and GeoJSON export."
        ),
    },
    {
        "name": "Viewer",
        "description": "Interactive Leaflet geospatial measurement visualizer and uploader.",
    },
    {
        "name": "Health",
        "description": "System health and service operational availability endpoints.",
    },
    {
        "name": "Root",
        "description": "Service index and documentation links.",
    },
]

API_DESCRIPTION = """
### Production Geospatial File Measurement API

A robust, enterprise-grade geospatial processing engine built on FastAPI,
SQLAlchemy 2.x, GeoPandas, PyOgrio, Shapely 2.x, and PyProj.

#### Core Capabilities:
* **Multi-Format Ingestion**: Ingests zipped Shapefiles (`.zip` containing `.shp`, `.shx`, `.dbf`)
  and Keyhole Markup Language (`.kml`) datasets.
* **Security Guardrails**: Hardened against Zip-Slip traversal, Zip-bomb denial of service,
  memory exhaustion, and invalid file signatures.
* **Geodetic Precision**: Automatically identifies optimal local UTM projections or
  Lambert Azimuthal Equal-Area (LAEA) projections for planar calculations with
  ellipsoidal geodesic (`pyproj.Geod`) cross-checks.
* **Dual Execution Modes**: Fast synchronous inline processing for datasets below 5 MB
  and asynchronous `BackgroundTasks` execution with HTTP 202 for large files.
* **Flexible Querying & Export**: Paginated measurement queries with attribute filtering
  and RFC 7946 GeoJSON `FeatureCollection` output.
"""


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    """Application lifespan context for initialization and cleanup."""
    init_db()
    settings.UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
    yield


app = FastAPI(
    title=settings.PROJECT_NAME,
    version=settings.VERSION,
    description=API_DESCRIPTION,
    openapi_tags=TAGS_METADATA,
    lifespan=lifespan,
    docs_url="/docs",
    redoc_url="/redoc",
)

# Cross-Origin Resource Sharing
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Global uniform error handlers
register_exception_handlers(app)


@app.middleware("http")
async def request_correlation_and_timing_middleware(request: Request, call_next):
    """Correlate request with unique ID and track execution latency."""
    incoming_id = request.headers.get("X-Request-ID")
    request_id = incoming_id if incoming_id else uuid.uuid4().hex
    token = request_id_ctx_var.set(request_id)
    start_time = time.perf_counter()

    try:
        response = await call_next(request)
        duration_ms = round((time.perf_counter() - start_time) * 1000, 2)
        response.headers["X-Request-ID"] = request_id
        response.headers["X-Process-Time-Ms"] = str(duration_ms)
        logger.info(
            f"{request.method} {request.url.path} -> {response.status_code} ({duration_ms}ms)"
        )
        return response
    except Exception as exc:
        duration_ms = round((time.perf_counter() - start_time) * 1000, 2)
        logger.error(
            f"{request.method} {request.url.path} unhandled exception ({duration_ms}ms): {exc}"
        )
        raise
    finally:
        request_id_ctx_var.reset(token)


# Include REST API routers
app.include_router(files_router, prefix="/api/files", tags=["Files"])

# Static directory mounting if directory exists
static_dir = Path("app/static") if Path("app/static").exists() else Path("static")
if static_dir.exists():
    app.mount("/static", StaticFiles(directory=str(static_dir)), name="static")


@app.get("/viewer", response_class=FileResponse, tags=["Viewer"])
def get_viewer() -> FileResponse:
    viewer_app = Path("app/static/viewer.html")
    viewer_file = viewer_app if viewer_app.exists() else Path("static/viewer.html")
    if not viewer_file.exists():
        raise HTTPException(
            status_code=404,
            detail="Viewer interface not found. static/viewer.html has not been initialized.",
        )
    return FileResponse(viewer_file, media_type="text/html")


@app.get("/health", response_model=HealthResponse, tags=["Health"])
def health_check() -> HealthResponse:
    """Check health and availability of the API service."""
    return HealthResponse(
        status="ok",
        app=settings.PROJECT_NAME,
        version=settings.VERSION,
    )


@app.get("/", tags=["Root"])
def root() -> dict[str, str]:
    """Root metadata and documentation navigator endpoint."""
    return {
        "name": settings.PROJECT_NAME,
        "version": settings.VERSION,
        "docs_url": "/docs",
        "redoc_url": "/redoc",
        "health_url": "/health",
        "viewer_url": "/viewer",
    }
