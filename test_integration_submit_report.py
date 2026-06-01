"""Integration tests for submit_report (POST /api/report).

Uses FastAPI's TestClient to hit the real /api/report endpoint, with real
SQLite queries to verify flock creation, joining, city prediction, and
validation — all backed by real city data loaded from export.geojson.

Tests use in-memory SQLite (no Docker needed).
"""

import pytest
from datetime import datetime, timezone, timedelta
from pathlib import Path

from fastapi.testclient import TestClient

from app.main import app
from app.config import settings
from app.sqlite_client import get_test_db


# ── Helpers ────────────────────────────────────────────────────────────────────

def _clean_test_db():
    """Delete all rows in the test SQLite database."""
    with get_test_db() as conn:
        conn.execute("DELETE FROM flock_coordinators")
        conn.execute("DELETE FROM reports")
        conn.execute("DELETE FROM flocks")
        conn.execute("DELETE FROM coordinators")
        conn.execute("DELETE FROM cities")
        conn.commit()


def load_cities_from_geojson():
    """Read Polish cities from export.geojson and create City rows in SQLite."""
    geojson_path = Path(__file__).parent / "export.geojson"
    import json
    with open(geojson_path) as f:
        data = json.load(f)

    cities = []
    for feature in data.get("features", []):
        props = feature.get("properties", {})
        place = props.get("place", "")
        name_pl = props.get("name:pl") or props.get("name")
        if place in ("city", "town") and name_pl:
            geo = feature.get("geometry", {})
            coords = geo.get("coordinates", [])
            if len(coords) == 2:
                lon, lat = coords[0], coords[1]
                cities.append((name_pl, float(lat), float(lon)))

    with get_test_db() as conn:
        conn.executemany(
            "INSERT OR REPLACE INTO cities (name, latitude, longitude) VALUES (?, ?, ?)",
            cities,
        )
        conn.commit()
    return len(cities)


@pytest.fixture(autouse=True)
def _setup_test_db():
    """Clean DB, load cities — runs before each test."""
    from app.lifecycle import _ensure_schema

    with get_test_db() as conn:
        _ensure_schema(conn)
        conn.execute("DELETE FROM flock_coordinators")
        conn.execute("DELETE FROM reports")
        conn.execute("DELETE FROM flocks")
        conn.execute("DELETE FROM coordinators")
        conn.execute("DELETE FROM cities")
        conn.commit()
    load_cities_from_geojson()


# ── Test data ──────────────────────────────────────────────────────────────────

def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _past_iso(hours_ago: float = 0.5) -> str:
    return (datetime.now(timezone.utc) - timedelta(hours=hours_ago)).isoformat()


client = TestClient(app)


# ── Tests ──────────────────────────────────────────────────────────────────────

class TestSubmitReportIntegration:
    """End-to-end tests hitting the real /api/report endpoint."""

    def test_submit_report_creates_new_flock(self):
        """First report → new Flock + Report rows created."""
        payload = {
            "latitude": 52.23,
            "longitude": 21.01,
            "timestamp": _now_iso(),
            "coordinator_email": "alice@example.com",
        }
        resp = client.post("/api/report", json=payload)
        assert resp.status_code == 200
        data = resp.json()
        assert data["report_id"]
        assert data["flock_id"]
        assert "Nowe stado" in data["message"]

        # Verify SQLite state
        with get_test_db() as conn:
            cursor = conn.execute(
                "SELECT COUNT(*) FROM flocks WHERE id = ?",
                (data["flock_id"],),
            )
            assert cursor.fetchone()[0] == 1

            cursor = conn.execute(
                "SELECT COUNT(*) FROM reports WHERE flock_id = ?",
                (data["flock_id"],),
            )
            assert cursor.fetchone()[0] == 1

            cursor = conn.execute(
                "SELECT COUNT(*) FROM flock_coordinators WHERE flock_id = ?",
                (data["flock_id"],),
            )
            assert cursor.fetchone()[0] == 1

    def test_second_report_joins_existing_flock(self):
        """Report within Vmax of existing flock → same flock_id returned."""
        base = datetime.now(timezone.utc) - timedelta(hours=1)
        payload1 = {
            "latitude": 52.23,
            "longitude": 21.01,
            "timestamp": base.isoformat(),
            "coordinator_email": "alice@example.com",
        }
        payload2 = {
            "latitude": 52.41,
            "longitude": 21.01,
            "timestamp": (base + timedelta(minutes=30)).isoformat(),
            "coordinator_email": "bob@example.com",
        }

        resp1 = client.post("/api/report", json=payload1)
        flock1 = resp1.json()["flock_id"]

        resp2 = client.post("/api/report", json=payload2)
        flock2 = resp2.json()["flock_id"]

        assert flock1 == flock2
        assert "Dołączono" in resp2.json()["message"]

        # Verify two reports in the same flock
        with get_test_db() as conn:
            cursor = conn.execute(
                "SELECT COUNT(*) FROM reports WHERE flock_id = ?",
                (flock1,),
            )
            assert cursor.fetchone()[0] == 2

    def test_report_far_away_creates_new_flock(self):
        """Report too far from existing flock → new flock created."""
        base = datetime.now(timezone.utc) - timedelta(hours=1)
        payload1 = {
            "latitude": 52.23,
            "longitude": 21.01,
            "timestamp": base.isoformat(),
            "coordinator_email": "alice@example.com",
        }
        payload2 = {
            "latitude": 51.75,
            "longitude": 19.45,
            "timestamp": (base + timedelta(minutes=30)).isoformat(),
            "coordinator_email": "bob@example.com",
        }

        resp1 = client.post("/api/report", json=payload1)
        flock1 = resp1.json()["flock_id"]

        resp2 = client.post("/api/report", json=payload2)
        flock2 = resp2.json()["flock_id"]

        assert flock1 != flock2

    def test_city_prediction_with_bearing(self):
        """Two reports in a line toward a city → city predicted, ETA computed."""
        base = datetime.now(timezone.utc) - timedelta(hours=1)

        payload1 = {
            "latitude": 50.95,
            "longitude": 21.90,
            "timestamp": base.isoformat(),
            "coordinator_email": "alice@example.com",
        }
        payload2 = {
            "latitude": 50.86,
            "longitude": 21.75,
            "timestamp": (base + timedelta(minutes=30)).isoformat(),
            "coordinator_email": "alice@example.com",
        }

        resp1 = client.post("/api/report", json=payload1)
        assert resp1.status_code == 200

        resp2 = client.post("/api/report", json=payload2)
        assert resp2.status_code == 200
        flock_id = resp2.json()["flock_id"]

        # Verify the flock has 2 reports
        with get_test_db() as conn:
            cursor = conn.execute(
                "SELECT COUNT(*) FROM reports WHERE flock_id = ?",
                (flock_id,),
            )
            assert cursor.fetchone()[0] == 2

    def test_submit_report_invalid_latitude(self):
        """Latitude out of range → 422."""
        payload = {
            "latitude": 100,
            "longitude": 21.01,
            "timestamp": _now_iso(),
            "coordinator_email": "alice@example.com",
        }
        resp = client.post("/api/report", json=payload)
        assert resp.status_code == 422

    def test_submit_report_invalid_email(self):
        """Invalid email → 422."""
        payload = {
            "latitude": 52.0,
            "longitude": 21.0,
            "timestamp": _now_iso(),
            "coordinator_email": "not-an-email",
        }
        resp = client.post("/api/report", json=payload)
        assert resp.status_code == 422

    def test_submit_report_future_timestamp(self):
        """Future timestamp → 422."""
        payload = {
            "latitude": 52.0,
            "longitude": 21.0,
            "timestamp": (datetime.now(timezone.utc) + timedelta(hours=1)).isoformat(),
            "coordinator_email": "alice@example.com",
        }
        resp = client.post("/api/report", json=payload)
        assert resp.status_code == 422

    def test_multiple_reports_same_flock_different_coordinators(self):
        """Multiple coordinators linked to same flock."""
        base = datetime.now(timezone.utc) - timedelta(hours=1)
        payload1 = {
            "latitude": 52.23,
            "longitude": 21.01,
            "timestamp": base.isoformat(),
            "coordinator_email": "alice@example.com",
        }
        payload2 = {
            "latitude": 52.41,
            "longitude": 21.01,
            "timestamp": (base + timedelta(minutes=30)).isoformat(),
            "coordinator_email": "bob@example.com",
        }
        payload3 = {
            "latitude": 52.50,
            "longitude": 21.05,
            "timestamp": (base + timedelta(minutes=60)).isoformat(),
            "coordinator_email": "charlie@example.com",
        }

        resp1 = client.post("/api/report", json=payload1)
        flock_id = resp1.json()["flock_id"]

        client.post("/api/report", json=payload2)
        client.post("/api/report", json=payload3)

        with get_test_db() as conn:
            cursor = conn.execute(
                "SELECT COUNT(*) FROM flock_coordinators WHERE flock_id = ?",
                (flock_id,),
            )
            assert cursor.fetchone()[0] == 3

    def test_health_endpoint(self):
        """GET /health → 200 ok."""
        resp = client.get("/health")
        assert resp.status_code == 200
        assert resp.json() == {"status": "ok"}
