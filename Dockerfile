# Production Multi-Stage / Hardened Dockerfile for Geospatial Measurement API
FROM python:3.12-slim

# Prevent Python from writing .pyc files and buffer stdout/stderr
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PORT=8000

# Install system runtime dependencies for GDAL, GEOS, PROJ, and healthchecks
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    gdal-bin \
    libgdal-dev \
    libgeos-dev \
    libproj-dev \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Create unprivileged application user and group for container security
RUN groupadd -r appgroup && useradd -r -g appgroup -d /app -s /sbin/nologin -c "Geospatial API User" appuser

WORKDIR /app

# Copy dependency definition and install Python packages
COPY requirements.txt .
RUN pip install --no-cache-dir --upgrade pip && \
    pip install --no-cache-dir -r requirements.txt

# Copy application source code, static assets, and reference samples
COPY app/ ./app/
COPY static/ ./static/
COPY samples/ ./samples/

# Create persistent storage directories and assign ownership to non-root appuser
RUN mkdir -p /app/data /app/uploads && \
    chown -R appuser:appgroup /app

# Drop root privileges
USER appuser

# Expose HTTP API port
EXPOSE 8000

# Container liveness health check probe
HEALTHCHECK --interval=20s --timeout=5s --start-period=5s --retries=3 \
    CMD sh -c 'curl -f http://localhost:${PORT:-8000}/health || exit 1'

# Launch production ASGI server (respects cloud $PORT env variable with 8000 fallback)
CMD ["sh", "-c", "uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8000}"]
