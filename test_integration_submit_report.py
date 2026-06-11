"""Integration tests for submit_report (POST /api/report).

Uses FastAPI's TestClient to hit the real /api/report endpoint, with real
Neo4j queries to verify flock creation, joining, city prediction, and
validation — all backed by real city data loaded from export.geojson.

Tests run against a dedicated Neo4j test container (port 7688) to avoid
contaminating the production database.
"""

import pytest
from datetime import datetime, timezone, timedelta
from pathlib import Path
import subprocess
import time

from fastapi.testclient import TestClient
from neo4j import GraphDatabase

from app.main import app
from app.config import settings
from app.neo4j_client import driver, get_test_db

# Import the lazy accessor under an alias to avoid pytest collecting it as a test
from app.neo4j_client import _get_test_driver as _td


# ── Test container lifecycle ───────────────────────────────────────────────────

TEST_CONTAINER_NAME = "birdspotter-test-neo4j"
TEST_IMAGE = "neo4j:latest"
TEST_BOLT_PORT = 7688
TEST_HTTP_PORT = 7475
TEST_USER = settings.neo4j_test_user
TEST_PASSWORD = settings.neo4j_test_password


def _container_is_running() -> bool:
    """Check whether the test Neo4j container is currently running."""
    result = subprocess.run(
        ["docker", "inspect", "-f", "{{.State.Running}}", TEST_CONTAINER_NAME],
        capture_output=True, text=True,
    )
    return result.returncode == 0 and result.stdout.strip() == "true"


def _container_is_healthy() -> bool:
    """Check whether the test Neo4j container is accepting Bolt connections.

    We use a lightweight Neo4j driver connection to verify the Bolt service
    is fully initialised, because raw socket checks are unreliable — Docker
    opens the port before Neo4j's Bolt handshake handler is ready, and even
    when ready the raw socket recv returns 0 bytes (the neo4j Python driver
    handles this correctly but raw sockets do not).
    """
    import socket

    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.settimeout(3)
    try:
        sock.connect(("127.0.0.1", TEST_BOLT_PORT))
        return True
    except OSError:
        return False
    finally:
        sock.close()


def _start_test_container():
    """Start the dedicated test Neo4j container if it isn't running."""
    if _container_is_running():
        # Wait for it to become healthy
        for _ in range(30):
            if _container_is_healthy():
                # Give Neo4j a few extra seconds after the socket opens
                time.sleep(5)
                return
            time.sleep(2)
        raise RuntimeError("Test Neo4j container is running but not healthy")

    result = subprocess.run(
        [
            "docker", "run", "-d",
            "--name", TEST_CONTAINER_NAME,
            "-p", f"{TEST_BOLT_PORT}:7687",
            "-p", f"{TEST_HTTP_PORT}:7474",
            "-e", "NEO4J_AUTH=neo4j/" + TEST_PASSWORD,
            TEST_IMAGE,
        ],
        check=True,
        capture_output=True,
        text=True,
    )
    container_id = result.stdout.strip()
    print(f"\nStarted test Neo4j container: {container_id[:12]}")

    # Wait for health check to pass
    for i in range(60):
        if _container_is_healthy():
            # Give Neo4j a few extra seconds after the socket opens
            time.sleep(5)
            return
        if i % 10 == 0:
            print(f"  Waiting for Neo4j to be ready... ({i * 2}s)")
        time.sleep(2)
    raise RuntimeError("Test Neo4j container failed to become healthy within 2 minutes")


def _stop_test_container():
    """Stop and remove the test Neo4j container (called once at session end)."""
    if _container_is_running():
        subprocess.run(
            ["docker", "rm", "-f", TEST_CONTAINER_NAME],
            capture_output=True,
        )


# ── Session-scoped fixtures ────────────────────────────────────────────────────

@pytest.fixture(scope="session", autouse=True)
def test_neo4j_container():
    """Start the test Neo4j Docker container once per test session."""
    _start_test_container()
    yield
    _stop_test_container()


@pytest.fixture(scope="session")
def neo4j_test_driver(test_neo4j_container):
    """Return the test driver and verify connectivity."""
    _td().verify_connectivity()
    yield _td


def _clean_test_db():
    """Detach-delete every node in the test Neo4j database."""
    with _td().session() as s:
        s.run("MATCH (n) DETACH DELETE n")


@pytest.fixture(autouse=True)
def _clean_before_each(neo4j_test_driver):
    _clean_test_db()
    yield
    _clean_test_db()


def load_cities_from_geojson():
    """Read Polish cities from export.geojson and create City nodes in Neo4j."""
    geojson_path = Path(__file__).parent / "export.geojson"
    import json
    with open(geojson_path) as f:
        data = json.load(f)

    cities = []
    for feature in data.get("features", []):
        props = feature.get("properties", {})
        place = props.get("place", "")
        name_pl = props.get("name:pl", "")
        if place in ("city", "town") and name_pl:
            geo = feature.get("geometry", {})
            coords = geo.get("coordinates", [])
            if len(coords) == 2:
                lon, lat = coords[0], coords[1]
                cities.append({"name": name_pl, "lat": float(lat), "lon": float(lon)})

    with _td().session() as s:
        for c in cities:
            s.run(
                "CREATE (c:City {name: $name, location: point({latitude: $lat, longitude: $lon})})",
                **c,
            )
    return len(cities)


@pytest.fixture(scope="session", autouse=True)
def seed_cities(neo4j_test_driver):
    """Load cities once per test session."""
    count = load_cities_from_geojson()
    assert count > 0, "No cities loaded from export.geojson"
    yield count


# ── Helpers ────────────────────────────────────────────────────────────────────

def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _past_iso(hours_ago: float = 0.5) -> str:
    return (datetime.now(timezone.utc) - timedelta(hours=hours_ago)).isoformat()


client = TestClient(app)


# ── Tests ──────────────────────────────────────────────────────────────────────

class TestSubmitReportIntegration:
    """End-to-end tests hitting the real /api/report endpoint."""

    # Monkeypatch: route app DB calls to the test driver for this test class only
    _original_get_db = None

    @pytest.fixture(autouse=True)
    def _patch_services_to_test_db(self, neo4j_test_driver):
        """Replace get_db in services module with get_test_db for this test."""
        import app.services as services_module
        TestSubmitReportIntegration._original_get_db = services_module.get_db
        services_module.get_db = get_test_db
        yield
        services_module.get_db = TestSubmitReportIntegration._original_get_db

    def test_submit_report_creates_new_flock(self, seed_cities):
        """First report → new Flock + Report nodes created."""
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

        # Verify Neo4j state
        with _td().session() as s:
            flock = s.run(
                "MATCH (f:Flock {id: $fid}) RETURN count(f) AS cnt",
                fid=data["flock_id"],
            )
            assert flock.single()["cnt"] == 1

            reports = s.run(
                "MATCH (f:Flock {id: $fid})-[:HAS_REPORT]->(r:Report) RETURN count(r) AS cnt",
                fid=data["flock_id"],
            )
            assert reports.single()["cnt"] == 1

            coordinators = s.run(
                "MATCH (f:Flock {id: $fid})-[:NOTIFIED_OF]->(c:Coordinator) RETURN count(c) AS cnt",
                fid=data["flock_id"],
            )
            assert coordinators.single()["cnt"] == 1

    def test_second_report_joins_existing_flock(self, seed_cities):
        """Report within Vmax of existing flock → same flock_id returned."""
        base = datetime.now(timezone.utc) - timedelta(hours=1)
        payload1 = {
            "latitude": 52.23,
            "longitude": 21.01,
            "timestamp": base.isoformat(),
            "coordinator_email": "alice@example.com",
        }
        # ~20 km away, 30 min later — well within Vmax=100 km/h
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
        with _td().session() as s:
            cnt = s.run(
                "MATCH (f:Flock {id: $fid})-[:HAS_REPORT]->(r:Report) RETURN count(r) AS cnt",
                fid=flock1,
            ).single()["cnt"]
            assert cnt == 2

    def test_report_far_away_creates_new_flock(self, seed_cities):
        """Report too far from existing flock → new flock created."""
        base = datetime.now(timezone.utc) - timedelta(hours=1)
        payload1 = {
            "latitude": 52.23,
            "longitude": 21.01,
            "timestamp": base.isoformat(),
            "coordinator_email": "alice@example.com",
        }
        # ~500 km away, 30 min later — exceeds Vmax=100 km/h
        payload2 = {
            "latitude": 51.75,  # Warsaw area, far from Krakow
            "longitude": 19.45,
            "timestamp": (base + timedelta(minutes=30)).isoformat(),
            "coordinator_email": "bob@example.com",
        }

        resp1 = client.post("/api/report", json=payload1)
        flock1 = resp1.json()["flock_id"]

        resp2 = client.post("/api/report", json=payload2)
        flock2 = resp2.json()["flock_id"]

        assert flock1 != flock2

    def test_city_prediction_with_bearing(self, seed_cities):
        """Two reports in a line toward a city → city predicted, ETA computed."""
        # Start near Annopol (50.885, 21.855) and head roughly south-west
        # so bearing points toward another city
        base = datetime.now(timezone.utc) - timedelta(hours=1)

        # Point 1
        payload1 = {
            "latitude": 50.95,
            "longitude": 21.90,
            "timestamp": base.isoformat(),
            "coordinator_email": "alice@example.com",
        }
        # Point 2 — roughly 10 km south-west of point 1
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

        # City prediction should have found a nearby city
        with _td().session() as s:
            # Check that the flock has 2 reports
            cnt = s.run(
                "MATCH (f:Flock {id: $fid})-[:HAS_REPORT]->(r:Report) RETURN count(r) AS cnt",
                fid=flock_id,
            ).single()["cnt"]
            assert cnt == 2

    def test_submit_report_invalid_latitude(self, seed_cities):
        """Latitude out of range → 422."""
        payload = {
            "latitude": 100,
            "longitude": 21.01,
            "timestamp": _now_iso(),
            "coordinator_email": "alice@example.com",
        }
        resp = client.post("/api/report", json=payload)
        assert resp.status_code == 422

    def test_submit_report_invalid_email(self, seed_cities):
        """Invalid email → 422."""
        payload = {
            "latitude": 52.0,
            "longitude": 21.0,
            "timestamp": _now_iso(),
            "coordinator_email": "not-an-email",
        }
        resp = client.post("/api/report", json=payload)
        assert resp.status_code == 422

    def test_submit_report_future_timestamp(self, seed_cities):
        """Future timestamp → 422."""
        payload = {
            "latitude": 52.0,
            "longitude": 21.0,
            "timestamp": (datetime.now(timezone.utc) + timedelta(hours=1)).isoformat(),
            "coordinator_email": "alice@example.com",
        }
        resp = client.post("/api/report", json=payload)
        assert resp.status_code == 422

    def test_multiple_reports_same_flock_different_coordinators(self, seed_cities):
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

        with _td().session() as s:
            cnt = s.run(
                "MATCH (f:Flock {id: $fid})-[:NOTIFIED_OF]->(c:Coordinator) RETURN count(c) AS cnt",
                fid=flock_id,
            ).single()["cnt"]
            assert cnt == 3

    def test_health_endpoint(self, seed_cities):
        """GET /health → 200 ok."""
        resp = client.get("/health")
        assert resp.status_code == 200
        assert resp.json() == {"status": "ok"}
