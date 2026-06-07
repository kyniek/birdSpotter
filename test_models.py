from app.models import ReportRequest, ReportResponse
from datetime import datetime, timezone, timedelta
import pytest


def test_valid_report_request():
    req = ReportRequest(
        latitude=52.23,
        longitude=21.01,
        coordinator_email="test@example.com",
    )
    assert req.latitude == 52.23
    assert req.coordinator_email == "test@example.com"


def test_missing_required_field():
    with pytest.raises(Exception):  # pydantic raises ValidationError
        ReportRequest(longitude=21.01, coordinator_email="test@example.com")


def test_latitude_out_of_range():
    with pytest.raises(Exception):
        ReportRequest(
            latitude=100,
            longitude=21.01,
            coordinator_email="test@example.com",
        )


def test_longitude_out_of_range():
    with pytest.raises(Exception):
        ReportRequest(
            latitude=50,
            longitude=200,
            coordinator_email="test@example.com",
        )


def test_invalid_email():
    with pytest.raises(Exception):
        ReportRequest(
            latitude=50,
            longitude=20,
            coordinator_email="not-an-email",
        )


def test_future_timestamp():
    with pytest.raises(Exception):
        ReportRequest(
            latitude=50,
            longitude=20,
            timestamp=datetime.now(timezone.utc) + timedelta(hours=1),
            coordinator_email="test@example.com",
        )


def test_past_timestamp():
    ts = datetime.now(timezone.utc) - timedelta(hours=1)
    req = ReportRequest(
        latitude=50,
        longitude=20,
        timestamp=ts,
        coordinator_email="test@example.com",
    )
    assert req.timestamp == ts


def test_response_model():
    resp = ReportResponse(
        report_id="r1",
        flock_id="f1",
        message="Nowe stado abc123",
    )
    assert resp.report_id == "r1"
    assert resp.message == "Nowe stado abc123"
