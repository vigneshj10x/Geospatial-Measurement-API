"""Script to generate realistic geospatial sample datasets for testing and demonstrations."""

import tempfile
import zipfile
from pathlib import Path

import geopandas as gpd
from shapely.geometry import LineString, Point, Polygon


def create_india_survey_plots_kml(output_path: Path) -> None:
    """Generate realistic Bengaluru survey plots KML with polygons, a line, and a point."""
    kml_content = """<?xml version="1.0" encoding="UTF-8"?>
<kml xmlns="http://www.opengis.net/kml/2.2">
  <Document>
    <name>Bengaluru Cadastral and Infrastructure Survey</name>
    <description>Realistic survey plots near Cubbon Park and Vidhana Soudha, Bengaluru</description>

    <!-- Polygon: Cubbon Park Survey Plot 101 -->
    <Placemark>
      <name>Cubbon Park North Plot</name>
      <description>Heritage park municipal sector A-1</description>
      <ExtendedData>
        <Data name="survey_id"><value>KA-BLR-2026-101</value></Data>
        <Data name="zone"><value>Central</value></Data>
        <Data name="land_use"><value>Recreational Park</value></Data>
      </ExtendedData>
      <Polygon>
        <extrude>1</extrude>
        <altitudeMode>clampToGround</altitudeMode>
        <outerBoundaryIs>
          <LinearRing>
            <coordinates>
              77.5900,12.9750,0
              77.5950,12.9750,0
              77.5950,12.9800,0
              77.5900,12.9800,0
              77.5900,12.9750,0
            </coordinates>
          </LinearRing>
        </outerBoundaryIs>
      </Polygon>
    </Placemark>

    <!-- Polygon: Vidhana Soudha Administrative Plot 102 -->
    <Placemark>
      <name>Vidhana Soudha Secretariat Plot</name>
      <description>State administrative complex</description>
      <ExtendedData>
        <Data name="survey_id"><value>KA-BLR-2026-102</value></Data>
        <Data name="zone"><value>Government Reserved</value></Data>
      </ExtendedData>
      <Polygon>
        <outerBoundaryIs>
          <LinearRing>
            <coordinates>
              77.5910,12.9790,0
              77.5940,12.9790,0
              77.5940,12.9820,0
              77.5910,12.9820,0
              77.5910,12.9790,0
            </coordinates>
          </LinearRing>
        </outerBoundaryIs>
      </Polygon>
    </Placemark>

    <!-- LineString: Dr. Ambedkar Veedhi Avenue -->
    <Placemark>
      <name>Dr. Ambedkar Veedhi Corridor</name>
      <description>Primary arterial roadway</description>
      <ExtendedData>
        <Data name="road_class"><value>Arterial</value></Data>
        <Data name="lanes"><value>6</value></Data>
      </ExtendedData>
      <LineString>
        <tessellate>1</tessellate>
        <coordinates>
          77.5880,12.9740,0
          77.5920,12.9780,0
          77.5945,12.9830,0
        </coordinates>
      </LineString>
    </Placemark>

    <!-- Point: Geodetic Survey Benchmark -->
    <Placemark>
      <name>GSI Benchmark Station BLR-01</name>
      <description>High precision geodetic GPS datum marker</description>
      <ExtendedData>
        <Data name="elevation_m"><value>920.5</value></Data>
        <Data name="authority"><value>Survey of India</value></Data>
      </ExtendedData>
      <Point>
        <coordinates>77.5925,12.9775,920.5</coordinates>
      </Point>
    </Placemark>
  </Document>
</kml>"""
    output_path.write_text(kml_content, encoding="utf-8")


def create_roads_lines_zip(output_path: Path) -> None:
    """Generate a Shapefile in projected CRS EPSG:32643 (UTM Zone 43N) containing roads."""
    # Coordinates in UTM Zone 43N meters around Bengaluru (Easting ~780,000, Northing ~1,435,000)
    line1 = LineString([(780000.0, 1435000.0), (781500.0, 1436200.0), (783000.0, 1437500.0)])
    line2 = LineString([(782000.0, 1434500.0), (782500.0, 1436000.0), (783500.0, 1437000.0)])
    line3 = LineString([(779500.0, 1436000.0), (781000.0, 1436500.0), (782200.0, 1437200.0)])

    gdf = gpd.GeoDataFrame(
        [
            {
                "road_id": "NH-44-EXP",
                "name": "Hosur Road Expressway",
                "lanes": 6,
                "surface": "Asphalt",
                "geometry": line1,
            },
            {
                "road_id": "ORR-EAST",
                "name": "Outer Ring Road East",
                "lanes": 8,
                "surface": "Concrete",
                "geometry": line2,
            },
            {
                "road_id": "MG-ROAD",
                "name": "Mahatma Gandhi Boulevard",
                "lanes": 4,
                "surface": "Asphalt",
                "geometry": line3,
            },
        ],
        crs="EPSG:32643",
    )

    with tempfile.TemporaryDirectory() as tmp_dir:
        tmp_path = Path(tmp_dir)
        shp_file = tmp_path / "roads_lines.shp"
        gdf.to_file(shp_file, engine="pyogrio")

        with zipfile.ZipFile(output_path, "w", zipfile.ZIP_DEFLATED) as zf:
            for file_entry in tmp_path.iterdir():
                zf.write(file_entry, arcname=file_entry.name)


def create_mixed_geometries_zip(output_path: Path) -> None:
    """Generate a multi-layer shapefile archive with Polygon, Line, and Point layers."""
    with tempfile.TemporaryDirectory() as tmp_dir:
        tmp_path = Path(tmp_dir)

        # 1. Parcels Layer (Polygons) with multilingual Unicode attributes
        poly1 = Polygon(
            [(77.58, 12.96), (77.60, 12.96), (77.60, 12.98), (77.58, 12.98), (77.58, 12.96)]
        )
        poly2 = Polygon(
            [(77.61, 12.97), (77.63, 12.97), (77.63, 12.99), (77.61, 12.99), (77.61, 12.97)]
        )
        gdf_polys = gpd.GeoDataFrame(
            [
                {
                    "plot_id": "BLR-001",
                    "land_name": "Lalbagh Botanical Zone",
                    "locality": "ಬೆಂಗಳೂರು",  # Kannada
                    "category": "Green Reserve",
                    "geometry": poly1,
                },
                {
                    "plot_id": "BLR-002",
                    "land_name": "Indiranagar Sector 2",
                    "locality": "இந்திரா நகர்",  # Tamil
                    "category": "Commercial Mixed",
                    "geometry": poly2,
                },
            ],
            crs="EPSG:4326",
        )
        gdf_polys.to_file(tmp_path / "parcels.shp", engine="pyogrio")

        # 2. Corridors Layer (LineStrings)
        line = LineString([(77.58, 12.96), (77.605, 12.975), (77.63, 12.99)])
        gdf_lines = gpd.GeoDataFrame(
            [
                {
                    "corridor_id": "METRO-PURPLE",
                    "name": "Namma Metro Purple Corridor",
                    "geometry": line,
                }
            ],
            crs="EPSG:4326",
        )
        gdf_lines.to_file(tmp_path / "corridors.shp", engine="pyogrio")

        # 3. Monuments Layer (Points)
        pt1 = Point(77.59, 12.97)
        pt2 = Point(77.62, 12.98)
        gdf_pts = gpd.GeoDataFrame(
            [
                {
                    "mon_id": "MON-1",
                    "name": "Historic Kempegowda Tower",
                    "geometry": pt1,
                },
                {
                    "mon_id": "MON-2",
                    "name": "Survey Control Station 9",
                    "geometry": pt2,
                },
            ],
            crs="EPSG:4326",
        )
        gdf_pts.to_file(tmp_path / "monuments.shp", engine="pyogrio")

        # Package all layers into one zip archive
        with zipfile.ZipFile(output_path, "w", zipfile.ZIP_DEFLATED) as zf:
            for file_entry in tmp_path.iterdir():
                zf.write(file_entry, arcname=file_entry.name)


def main() -> None:
    """Generate all sample files in the samples directory."""
    samples_dir = Path(__file__).resolve().parent.parent / "samples"
    samples_dir.mkdir(parents=True, exist_ok=True)

    kml_path = samples_dir / "india_survey_plots.kml"
    roads_zip = samples_dir / "roads_lines.zip"
    mixed_zip = samples_dir / "mixed_geometries.zip"

    print(f"Generating {kml_path}...")
    create_india_survey_plots_kml(kml_path)

    print(f"Generating {roads_zip}...")
    create_roads_lines_zip(roads_zip)

    print(f"Generating {mixed_zip}...")
    create_mixed_geometries_zip(mixed_zip)

    print("Successfully generated all sample datasets in samples/!")


if __name__ == "__main__":
    main()
