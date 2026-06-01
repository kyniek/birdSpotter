"""Tests for app/main.py (FastAPI endpoints)."""

import pytest
from unittest.mock import patch, MagicMock
from datetime import datetime, timezone, timedelta
from fastapi.testclient import TestClient

from app.main import app
from app.sqlite_client import get_test_db


@pytest.fixture(autouse=True)
def clean_db():
    """Clean DB before each test."""
    from app.lifecycle import _ensure_schema
    with get_test_db() as conn:
        _ensure_schema(conn)
        conn.execute("DELETE FROM flock_coordinators")
        conn.execute("DELETE FROM reports")
        conn.execute("DELETE FROM flocks")
        conn.execute("DELETE FROM coordinators")
        conn.execute("DELETE FROM cities")
        conn.commit()
    yield
    with get_test_db() as conn:
        conn.execute("DELETE FROM flock_coordinators")
        conn.execute("DELETE FROM reports")
        conn.execute("DELETE FROM flocks")
        conn.execute("DELETE FROM coordinators")
        conn.execute("DELETE FROM cities")
        conn.commit()


client = TestClient(app)


def test_health():
    """GET /health should return 200 with status ok."""
    resp = client.get("/health")
    assert resp.status_code == 200
    assert resp.json() == {"status": "ok"}


def test_submit_report_valid():
    """POST /api/report with valid data should return 200."""
    now = datetime.now(timezone.utc)
    payload = {
        "latitude": 52.23,
        "longitude": 21.01,
        "timestamp": now.isoformat(),
        "coordinator_email": "test@example.com",
    }
    mock_instance = MagicMock()
    mock_instance.__enter__ = MagicMock(return_value=mock_instance)
    mock_instance.__exit__ = MagicMock(return_value=False)
    with patch("smtplib.SMTP", return_value=mock_instance):
        resp = client.post("/api/report", json=payload)

    assert resp.status_code == 200
    data = resp.json()
    assert data["report_id"] is not None
    assert data["flock_id"] is not None
    assert "Nowe stado" in data["message"] or "Dołączono" in data["message"]


def test_submit_report_invalid_latitude():
    """POST /api/report with latitude out of range should return 422."""
    payload = {
        "latitude": 100,
        "longitude": 21.01,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "coordinator_email": "test@example.com",
    }
    resp = client.post("/api/report", json=payload)
    assert resp.status_code == 422


def test_submit_report_invalid_email():
    """POST /api/report with invalid email should return 422."""
    payload = {
        "latitude": 52.0,
        "longitude": 21.0,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "coordinator_email": "not-an-email",
    }
    resp = client.post("/api/report", json=payload)
    assert resp.status_code == 422


def test_submit_report_future_timestamp():
    """POST /api/report with future timestamp should return 422."""
    payload = {
        "latitude": 52.0,
        "longitude": 21.0,
        "timestamp": (datetime.now(timezone.utc) + timedelta(hours=1)).isoformat(),
        "coordinator_email": "test@example.com",
    }
    resp = client.post("/api/report", json=payload)
    assert resp.status_code == 422


def test_submit_report_second_report_same_flock():
    """Second report close to first should be assigned to same flock."""
    mock_instance = MagicMock()
    mock_instance.__enter__ = MagicMock(return_value=mock_instance)
    mock_instance.__exit__ = MagicMock(return_value=False)

    base = datetime.now(timezone.utc) - timedelta(hours=1)
    payload1 = {
        "latitude": 52.23,
        "longitude": 21.01,
        "timestamp": base.isoformat(),
        "coordinator_email": "test@example.com",
    }

    payload2 = {
        "latitude": 52.41,
        "longitude": 21.01,
        "timestamp": (base + timedelta(minutes=30)).isoformat(),
        "coordinator_email": "test2@example.com",
    }

    with patch("smtplib.SMTP", return_value=mock_instance):
        resp1 = client.post("/api/report", json=payload1)
        flock1 = resp1.json()["flock_id"]

        resp2 = client.post("/api/report", json=payload2)
        flock2 = resp2.json()["flock_id"]

    assert flock1 == flock2
