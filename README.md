# Geospatial Measurement API

[![CI Pipeline](https://github.com/vigneshj10x/Geospatial-Measurement-API/actions/workflows/ci.yml/badge.svg)](https://github.com/vigneshj10x/Geospatial-Measurement-API/actions/workflows/ci.yml)
[![Python Version](https://img.shields.io/badge/python-3.11%20%7C%203.14-blue.svg)](https://www.python.org/)
[![FastAPI](https://img.shields.io/badge/FastAPI-0.141+-009688.svg?logo=fastapi&logoColor=white)](https://fastapi.tiangolo.com)
[![Coverage](https://img.shields.io/badge/coverage->85%25-brightgreen.svg)](https://pytest-cov.readthedocs.io/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)

A production-grade geospatial measurement microservice built on FastAPI, SQLAlchemy 2.x, GeoPandas, PyOgrio, Shapely 2.x, and PyProj. It accurately calculates planar area and linear distance from uploaded ESRI Shapefiles (`.zip`) and Keyhole Markup Language (`.kml`) datasets using adaptive local projections cross-checked with ellipsoidal geodesics.

---

## Key Features

- **Multi-Format Ingestion**: Ingests zipped Shapefiles (`.shp`, `.shx`, `.dbf`, `.prj`) and KML files (with native PyOgrio and fallback XML streaming parsing).
- **Security Guardrails**: Hardened against Zip-Slip path traversal, decompression bombs (100 MB / 100x ratio limits), and malicious file signatures.
- **Adaptive Precision Engine**:
  - Automatically selects local UTM zones (`EPSG:326xx` / `EPSG:327xx`) from feature centroids.
  - Switches to custom centroid-centered Lambert Azimuthal Equal-Area (LAEA) projections for multi-zone or wide (>6° lon) geometries.
  - Polar fallback to World Cylindrical Equal Area (`EPSG:6933`).
  - Cross-checks planar calculations against WGS84 ellipsoidal geodesics (`pyproj.Geod`) reporting relative delta percentage (`±%`).
- **Flexible Execution Modes**: Synchronous inline processing for files under 5 MB (or with `?wait=true`), and asynchronous FastAPI `BackgroundTasks` (HTTP 202) for large datasets.
- **Interactive Leaflet Viewer**: Built-in zero-build web viewer at `GET /viewer` supporting drag-and-drop uploads, color-coded geometry layers, dynamic unit conversions (`m²`, `ha`, `acres`, `km²`), and popup metrics.
- **Enterprise Observability**: Correlated structured logging with `X-Request-ID`, execution stage timers (`read_ms`, `meas_ms`, `db_ms`), and database duration tracking.

---

## Quickstart

### 1. Local Setup

```bash
# Clone repository
git clone https://github.com/vigneshj10x/Geospatial-Measurement-API.git
cd Geospatial-Measurement-API

# Install dependencies
make install
# or: pip install -r requirements.txt -r requirements-dev.txt

# Run server with hot-reload
make run
# Server will start on http://localhost:8000
```

### 2. Docker & Docker Compose

```bash
# Build and run with persistent volumes
make docker-up
# or: docker compose up -d --build

# View container logs
docker compose logs -f

# Shut down container
make docker-down
```

---

## Interactive Endpoints

- **Map Viewer**: [http://localhost:8000/viewer](http://localhost:8000/viewer)
- **Interactive Swagger UI**: [http://localhost:8000/docs](http://localhost:8000/docs)
- **ReDoc Documentation**: [http://localhost:8000/redoc](http://localhost:8000/redoc)
- **Health Check**: [http://localhost:8000/health](http://localhost:8000/health)

---

## API Summary

| Method | Endpoint | Description |
|---|---|---|
| `POST` | `/api/files/` | Ingest Shapefile archive (`.zip`) or `.kml`. Supports `?wait=true`. |
| `GET` | `/api/files/` | Paginated listing of uploaded datasets. |
| `GET` | `/api/files/{id}/` | Detailed metadata, processing duration, geometry counts, and summary totals. |
| `GET` | `/api/files/{id}/measurements/` | Paginated measurements. Supports `?geometry_type=`, `?status=`, and `?format=geojson`. |
| `DELETE` | `/api/files/{id}/` | Delete dataset and associated feature records. |
| `GET` | `/viewer` | Single-page Leaflet web map viewer with dynamic unit switcher. |
| `GET` | `/health` | Service health status. |

---

## Development & Testing

```bash
# Run Ruff lint checks
make lint

# Run full test suite with services coverage
make test

# Format code
make format
```
