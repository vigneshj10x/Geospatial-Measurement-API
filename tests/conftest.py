"""Pytest configuration and programmatic geospatial test fixtures."""

import zipfile
from collections.abc import Generator
from pathlib import Path

import geopandas as gpd
import pytest
from shapely.geometry import LineString, Polygon
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool
from starlette.testclient import TestClient

import app.db
from app.db import Base, get_db

# In-memory SQLite database for high-speed isolated tests
TEST_DATABASE_URL = "sqlite:///:memory:"

test_engine = create_engine(
    TEST_DATABASE_URL,
    connect_args={"check_same_thread": False},
    poolclass=StaticPool,
)

app.db.SessionLocal.configure(bind=test_engine)

TestingSessionLocal = sessionmaker(
    bind=test_engine,
    autocommit=False,
    autoflush=False,
    expire_on_commit=False,
)


@pytest.fixture(autouse=True)
def setup_test_database() -> Generator[None, None, None]:
    """Create all database tables before test and drop afterwards."""
    Base.metadata.create_all(bind=test_engine)
    yield
    Base.metadata.drop_all(bind=test_engine)


@pytest.fixture
def db_session() -> Generator[Session, None, None]:
    """Provide a direct database session for test queries."""
    session = TestingSessionLocal()
    try:
        yield session
    finally:
        session.close()


@pytest.fixture
def override_get_db(db_session: Session) -> Generator[None, None, None]:
    """Override FastAPI get_db dependency with test database session."""
    from app.main import app

    def _override() -> Generator[Session, None, None]:
        yield db_session

    app.dependency_overrides[get_db] = _override
    yield
    app.dependency_overrides.pop(get_db, None)


@pytest.fixture
def client(override_get_db: None) -> Generator[TestClient, None, None]:
    """Provide a TestClient connected to the FastAPI application."""
    from app.main import app

    with TestClient(app) as test_client:
        yield test_client


# =====================================================================
# Programmatic Geospatial Fixtures
# =====================================================================


@pytest.fixture
def valid_shapefile_zip(tmp_path: Path) -> Path:
    """Generate a valid zipped shapefile with a Polygon feature."""
    poly = Polygon([(2.34, 48.85), (2.36, 48.85), (2.36, 48.87), (2.34, 48.87), (2.34, 48.85)])
    gdf = gpd.GeoDataFrame(
        [{"name": "Paris Parc", "category": "park", "geometry": poly}],
        crs="EPSG:4326",
    )
    shp_dir = tmp_path / "valid_shp_source"
    shp_dir.mkdir(parents=True, exist_ok=True)
    shp_file = shp_dir / "parcels.shp"
    gdf.to_file(shp_file, engine="pyogrio")

    zip_path = tmp_path / "valid_parcels.zip"
    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
        for f in shp_dir.iterdir():
            zf.write(f, arcname=f.name)
    return zip_path


@pytest.fixture
def shapefile_missing_prj_zip(tmp_path: Path) -> Path:
    """Generate a valid shapefile zip lacking a .prj file."""
    poly = Polygon([(0.0, 0.0), (1.0, 0.0), (1.0, 1.0), (0.0, 1.0), (0.0, 0.0)])
    gdf = gpd.GeoDataFrame([{"name": "No PRJ Zone", "geometry": poly}], crs="EPSG:4326")

    shp_dir = tmp_path / "no_prj_source"
    shp_dir.mkdir(parents=True, exist_ok=True)
    shp_file = shp_dir / "unprojected.shp"
    gdf.to_file(shp_file, engine="pyogrio")

    zip_path = tmp_path / "missing_prj.zip"
    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
        for f in shp_dir.iterdir():
            # Deliberately exclude .prj file
            if f.suffix.lower() != ".prj":
                zf.write(f, arcname=f.name)
    return zip_path


@pytest.fixture
def shapefile_missing_dbf_zip(tmp_path: Path) -> Path:
    """Generate an incomplete shapefile zip missing the mandatory .dbf component."""
    zip_path = tmp_path / "missing_dbf.zip"
    with zipfile.ZipFile(zip_path, "w") as zf:
        zf.writestr("layer.shp", b"dummy shp content")
        zf.writestr("layer.shx", b"dummy shx content")
        # .dbf is omitted
    return zip_path


@pytest.fixture
def multi_shapefile_zip(tmp_path: Path) -> Path:
    """Generate a zip archive containing multiple shapefiles (parcels & trails)."""
    poly = Polygon([(10.0, 10.0), (11.0, 10.0), (11.0, 11.0), (10.0, 11.0), (10.0, 10.0)])
    gdf_poly = gpd.GeoDataFrame([{"name": "Parcel 1", "geometry": poly}], crs="EPSG:4326")

    line = LineString([(10.0, 10.0), (10.5, 10.5), (11.0, 11.0)])
    gdf_line = gpd.GeoDataFrame([{"name": "Trail 1", "geometry": line}], crs="EPSG:4326")

    src_dir = tmp_path / "multi_shp_source"
    src_dir.mkdir(parents=True, exist_ok=True)
    gdf_poly.to_file(src_dir / "parcels.shp", engine="pyogrio")
    gdf_line.to_file(src_dir / "trails.shp", engine="pyogrio")

    zip_path = tmp_path / "multi_shapefile.zip"
    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
        for f in src_dir.iterdir():
            zf.write(f, arcname=f.name)
    return zip_path


@pytest.fixture
def shapefile_with_null_geom_zip(tmp_path: Path) -> Path:
    """Generate a shapefile containing a valid polygon and a null/empty geometry."""
    poly = Polygon([(0.0, 0.0), (1.0, 0.0), (1.0, 1.0), (0.0, 1.0), (0.0, 0.0)])
    empty_poly = Polygon()
    gdf = gpd.GeoDataFrame(
        [
            {"name": "Valid Parcel", "geometry": poly},
            {"name": "Empty Parcel", "geometry": empty_poly},
        ],
        crs="EPSG:4326",
    )
    src_dir = tmp_path / "null_geom_source"
    src_dir.mkdir(parents=True, exist_ok=True)
    gdf.to_file(src_dir / "nulls.shp", engine="pyogrio")

    zip_path = tmp_path / "null_geometries.zip"
    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
        for f in src_dir.iterdir():
            zf.write(f, arcname=f.name)
    return zip_path


@pytest.fixture
def zip_slip_archive(tmp_path: Path) -> Path:
    """Generate an archive with a zip-slip directory traversal path."""
    zip_path = tmp_path / "zip_slip.zip"
    with zipfile.ZipFile(zip_path, "w") as zf:
        zf.writestr("../../etc/passwd", "root:x:0:0:")
    return zip_path


@pytest.fixture
def corrupt_zip_file(tmp_path: Path) -> Path:
    """Generate a corrupt non-zip file with a .zip extension."""
    corrupt_path = tmp_path / "corrupt.zip"
    corrupt_path.write_bytes(b"CORRUPTED_BINARY_NOT_A_ZIP_ARCHIVE_HEADER")
    return corrupt_path


@pytest.fixture
def wrong_extension_file(tmp_path: Path) -> Path:
    """Generate a file with an unsupported extension (.geojson)."""
    wrong_path = tmp_path / "dataset.geojson"
    wrong_path.write_text('{"type": "FeatureCollection", "features": []}', encoding="utf-8")
    return wrong_path


@pytest.fixture
def valid_kml_file(tmp_path: Path) -> Path:
    """Generate a standard valid KML file with Polygon and Point placemarks."""
    kml_text = """<?xml version="1.0" encoding="UTF-8"?>
<kml xmlns="http://www.opengis.net/kml/2.2">
  <Document>
    <name>Valid KML Sample</name>
    <Placemark>
      <name>Eiffel Tower Parcel</name>
      <description>Heritage monument</description>
      <Polygon>
        <outerBoundaryIs>
          <LinearRing>
            <coordinates>
              2.294,48.858,35
              2.295,48.858,35
              2.295,48.859,35
              2.294,48.859,35
              2.294,48.858,35
            </coordinates>
          </LinearRing>
        </outerBoundaryIs>
      </Polygon>
    </Placemark>
    <Placemark>
      <name>Viewpoint Marker</name>
      <Point>
        <coordinates>2.2945,48.8585,50</coordinates>
      </Point>
    </Placemark>
  </Document>
</kml>"""
    kml_path = tmp_path / "eiffel.kml"
    kml_path.write_text(kml_text, encoding="utf-8")
    return kml_path


@pytest.fixture
def multi_folder_kml_file(tmp_path: Path) -> Path:
    """Generate a KML file containing multiple distinct folders/layers."""
    kml_text = """<?xml version="1.0" encoding="UTF-8"?>
<kml xmlns="http://www.opengis.net/kml/2.2">
  <Document>
    <name>Multi-Folder Project</name>
    <Folder>
      <name>Northern_Reserve</name>
      <Placemark>
        <name>North Lake</name>
        <Polygon>
          <outerBoundaryIs>
            <LinearRing>
              <coordinates>
                12.0,55.0,0
                12.1,55.0,0
                12.1,55.1,0
                12.0,55.1,0
                12.0,55.0,0
              </coordinates>
            </LinearRing>
          </outerBoundaryIs>
        </Polygon>
      </Placemark>
    </Folder>
    <Folder>
      <name>Southern_Trail</name>
      <Placemark>
        <name>Main Ridge Line</name>
        <LineString>
          <coordinates>
            12.0,54.9,0
            12.05,54.95,0
            12.1,54.9,0
          </coordinates>
        </LineString>
      </Placemark>
    </Folder>
  </Document>
</kml>"""
    kml_path = tmp_path / "multi_folder.kml"
    kml_path.write_text(kml_text, encoding="utf-8")
    return kml_path
