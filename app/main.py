"""FastAPI application entrypoint, middleware, routers, and OpenAPI documentation."""

from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.files import router as files_router
from app.config import settings
from app.db import init_db
from app.exceptions import register_exception_handlers
from app.schemas import HealthResponse

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

# Include REST API routers
app.include_router(files_router, prefix="/api/files", tags=["Files"])


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
    }
