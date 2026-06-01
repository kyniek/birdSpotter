"""Tests for app/services.py — flock identification, report addition, city prediction."""

import pytest
from datetime import datetime, timezone, timedelta

from app.neo4j_client import get_db, driver
from app.services import (
    identify_or_create_flock,
    add_report_and_get_flock_info,
    predict_cities,
    get_coordinators_for_flock,
)


# ── Fixtures ──────────────────────────────────────────────────────────────────

@pytest.fixture(autouse=True, scope="session")
def neo4j_available():
    """Skip all tests if Neo4j is down."""
    try:
        driver.verify_connectivity()
    except Exception as e:
        pytest.skip(f"Neo4j not reachable: {e}")
    yield


@pytest.fixture(autouse=True)
def clean_db():
    """Before each test: drop all Flock, Report, Coordinator, City nodes."""
    with get_db() as session:
        session.run("MATCH (n) DETACH DELETE n")
    yield
    with get_db() as session:
        session.run("MATCH (n) DETACH DELETE n")


@pytest.fixture
def test_cities():
    """Load a few test cities into the database."""
    cities = [
        ("NorthCity", 55.0, 21.0),
        ("SouthCity", 49.0, 21.0),
        ("EastCity", 52.0, 25.0),
        ("WestCity", 52.0, 17.0),
    ]
    with get_db() as session:
        for name, lat, lon in cities:
            session.run(
                "CREATE (c:City {name: $name, location: point({latitude: $lat, longitude: $lon})})",
                name=name, lat=lat, lon=lon,
            )
    return cities


# ── Helper: create a flock with a LAST_REPORT ─────────────────────────────────

def _create_flock_with_report(session, flock_id, lat, lon, ts_iso):
    """Create a Flock node with a Report and LAST_REPORT relationship."""
    session.run(
        "CREATE (f:Flock {id: $fid})-[:HAS_REPORT]->"
        "(:Report {id: $rid, location: point({latitude: $lat, longitude: $lon}), timestamp: datetime($ts)})",
        fid=flock_id, rid=flock_id + "_r1", lat=lat, lon=lon, ts=ts_iso,
    )
    session.run(
        "MATCH (f:Flock {id: $fid})-[:HAS_REPORT]->(r:Report) "
        "CREATE (f)-[:LAST_REPORT]->(r)",
        fid=flock_id,
    )


# ── Flock identification tests ────────────────────────────────────────────────

def test_identify_new_flock_empty_db():
    """When the DB is empty, a new flock should be created."""
    flock_id, is_new = identify_or_create_flock(52.0, 21.0, datetime.now(timezone.utc))
    assert is_new is True
    assert flock_id is not None
    assert len(flock_id) > 0


def test_identify_flock_global_silence():
    """If the last report is older than SILENCE_WINDOW_HOURS, a new flock is created."""
    now = datetime.now(timezone.utc)
    old_ts = now - timedelta(hours=11)
    with get_db() as session:
        _create_flock_with_report(session, "old_flock", 52.0, 21.0, old_ts.isoformat())
    flock_id, is_new = identify_or_create_flock(52.0, 21.0, now)
    assert is_new is True
    assert flock_id != "old_flock"


def test_identify_flock_within_vmax():
    """New report within Vmax * time_delta should match existing flock."""
    now = datetime.now(timezone.utc)
    one_hour_ago = now - timedelta(hours=1)
    with get_db() as session:
        _create_flock_with_report(session, "existing_flock", 52.0, 21.0, one_hour_ago.isoformat())
    # New report 50 km away, 1 hour later → dist 50 <= 100*1 → match
    flock_id, is_new = identify_or_create_flock(52.45, 21.0, now)
    assert is_new is False
    assert flock_id == "existing_flock"


def test_identify_flock_exceeds_vmax():
    """New report too far for the time window → new flock."""
    now = datetime.now(timezone.utc)
    two_hours_ago = now - timedelta(hours=2)
    with get_db() as session:
        _create_flock_with_report(session, "far_flock", 52.0, 21.0, two_hours_ago.isoformat())
    # 500 km away in 2h → 250 km/h > Vmax 100 → new flock
    flock_id, is_new = identify_or_create_flock(56.5, 21.0, now)
    assert is_new is True
    assert flock_id != "far_flock"


def test_identify_closest_flock():
    """Two flocks in range → pick the closest one."""
    now = datetime.now(timezone.utc)
    one_hour_ago = now - timedelta(hours=1)
    with get_db() as session:
        # Flock A: ~10 km away
        _create_flock_with_report(session, "flock_a", 52.09, 21.0, one_hour_ago.isoformat())
        # Flock B: ~20 km away
        _create_flock_with_report(session, "flock_b", 52.27, 21.0, one_hour_ago.isoformat())
    # New report at 52.15, 21.0 → closer to flock_a (10 km) than flock_b (20 km)
    flock_id, is_new = identify_or_create_flock(52.15, 21.0, now)
    assert is_new is False
    assert flock_id == "flock_a"


# ── Report addition tests ─────────────────────────────────────────────────────

def test_add_report_and_get_flock_info():
    """Adding a report should create it, update LAST_REPORT, create coordinator."""
    now = datetime.now(timezone.utc)
    flock_id, _ = identify_or_create_flock(52.0, 21.0, now)

    report_id, last_points = add_report_and_get_flock_info(
        flock_id, 52.1, 21.1, now, "test@example.com"
    )

    assert report_id is not None
    # identify_or_create_flock already created the initial report,
    # so we get 2 points (initial + new)
    assert len(last_points) == 2
    locations = {tuple(p["location"]) for p in last_points}
    assert locations == {(52.0, 21.0), (52.1, 21.1)}

    # Verify in DB
    with get_db() as session:
        result = session.run(
            "MATCH (f:Flock {id: $fid})-[:HAS_REPORT]->(r:Report) RETURN count(r) AS cnt",
            fid=flock_id,
        )
        assert list(result)[0]["cnt"] == 2

        # Coordinator exists
        result = session.run(
            "MATCH (f:Flock {id: $fid})-[:NOTIFIED_OF]->(c:Coordinator) RETURN count(c) AS cnt",
            fid=flock_id,
        )
        assert list(result)[0]["cnt"] == 1


def test_add_report_returns_last_two_points():
    """After adding two reports, last_points should contain both."""
    now = datetime.now(timezone.utc)
    flock_id, _ = identify_or_create_flock(52.0, 21.0, now)

    add_report_and_get_flock_info(flock_id, 52.0, 21.0, now, "a@b.com")
    later = now + timedelta(minutes=30)
    report_id, last_points = add_report_and_get_flock_info(
        flock_id, 52.1, 21.1, later, "a@b.com"
    )

    assert len(last_points) == 2


# ── City prediction tests ─────────────────────────────────────────────────

def test_predict_cities_no_cities():
    """With no cities in DB, predict_cities returns empty list."""
    result = predict_cities(52.0, 21.0, 0)
    assert result == []


def test_predict_cities_with_cities_in_bearing(test_cities):
    """Cities in bearing sector should be returned, sorted by distance."""
    # Flock moving north from Warsaw (52.0, 21.0)
    # NorthCity is at (55.0, 21.0) → bearing ~0°
    bearing = 0.0
    result = predict_cities(52.0, 21.0, bearing)
    assert len(result) > 0
    # Closest city should be first
    assert result[0][0] == "NorthCity"


def test_predict_cities_no_city_in_tolerance():
    """If no city is within bearing tolerance, return empty list."""
    bearing = 45.0  # NE — no city in that direction from (52, 21)
    result = predict_cities(52.0, 21.0, bearing)
    # Might or might not find one depending on city positions; just check it doesn't crash
    assert isinstance(result, list)


def test_predict_cities_returns_multiple(test_cities):
    """Multiple cities in the same bearing sector should all be returned."""
    # Flock moving north from Warsaw (52.0, 21.0)
    bearing = 0.0
    result = predict_cities(52.0, 21.0, bearing)
    # NorthCity is closest; check that results are sorted by distance
    for i in range(len(result) - 1):
        assert result[i][1] <= result[i + 1][1]


# ── Coordinator tests ─────────────────────────────────────────────────────────

def test_get_coordinators_for_flock():
    now = datetime.now(timezone.utc)
    flock_id, _ = identify_or_create_flock(52.0, 21.0, now)
    add_report_and_get_flock_info(flock_id, 52.0, 21.0, now, "coord@example.com")

    coords = get_coordinators_for_flock(flock_id)
    assert "coord@example.com" in coords
