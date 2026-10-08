"""Tests for structured logging, request correlation ID, and processing duration recording."""

import uuid
from pathlib import Path

from starlette.testclient import TestClient

from app.logger import RequestIdFilter, request_id_ctx_var
from app.models import UploadedFile
from app.services.processor import process_file


def test_request_id_filter_injects_contextual_id():
    """RequestIdFilter attaches the current contextvar request_id to LogRecord."""
    test_id = "test-uuid-12345"
    token = request_id_ctx_var.set(test_id)
    try:
        filter_instance = RequestIdFilter()
        import logging
        record = logging.LogRecord(
            name="test", level=logging.INFO, pathname=__file__, lineno=10,
            msg="test message", args=(), exc_info=None
        )
        assert filter_instance.filter(record) is True
        assert getattr(record, "request_id", None) == test_id
    finally:
        request_id_ctx_var.reset(token)


def test_api_returns_request_id_and_timing_headers(client: TestClient):
    """Every HTTP response includes X-Request-ID and X-Process-Time-Ms headers."""
    custom_req_id = "custom-req-id-789"
    resp = client.get("/health", headers={"X-Request-ID": custom_req_id})
    assert resp.status_code == 200
    assert resp.headers["X-Request-ID"] == custom_req_id
    assert "X-Process-Time-Ms" in resp.headers
    assert float(resp.headers["X-Process-Time-Ms"]) >= 0.0

    # Auto-generated request ID if omitted
    resp_auto = client.get("/health")
    assert resp_auto.status_code == 200
    assert "X-Request-ID" in resp_auto.headers
    assert len(resp_auto.headers["X-Request-ID"]) > 0


def test_processing_duration_ms_recorded_in_file_record(db_session):
    """Processing a dataset populates processing_duration_ms > 0 in the database record."""
    kml_content = """<?xml version="1.0" encoding="UTF-8"?>
<kml xmlns="http://www.opengis.net/kml/2.2">
  <Document>
    <Placemark>
      <name>Small Polygon</name>
      <Polygon>
        <outerBoundaryIs>
          <LinearRing>
            <coordinates>
              77.59,12.97,0 77.60,12.97,0 77.60,12.98,0 77.59,12.98,0 77.59,12.97,0
            </coordinates>
          </LinearRing>
        </outerBoundaryIs>
      </Polygon>
    </Placemark>
  </Document>
</kml>"""
    test_kml_path = Path("tests") / "test_logging_sample.kml"
    test_kml_path.write_text(kml_content, encoding="utf-8")

    try:
        file_id = str(uuid.uuid4())
        file_record = UploadedFile(
            id=file_id,
            filename="test_logging_sample.kml",
            file_type="kml",
            status="PENDING",
            size_bytes=len(kml_content),
            storage_path=str(test_kml_path),
            feature_count=0,
            warnings=[],
        )
        db_session.add(file_record)
        db_session.commit()

        processed = process_file(file_id, db_session)
        assert processed.status == "COMPLETED"
        assert processed.processing_duration_ms is not None
        assert processed.processing_duration_ms > 0.0
    finally:
        if test_kml_path.exists():
            test_kml_path.unlink()
