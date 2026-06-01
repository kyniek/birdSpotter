"""Tests for app/services.py — flock identification, report addition, city prediction."""

import pytest
from datetime import datetime, timezone, timedelta

from app.sqlite_client import get_test_db
from app.services import (
    identify_or_create_flock,
    add_report_and_get_flock_info,
    predict_cities,
    get_coordinators_for_flock,
)


# ── Fixtures ──────────────────────────────────────────────────────────────────

@pytest.fixture(autouse=True)
def clean_db():
    """Before each test: ensure schema exists, then delete all rows."""
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


@pytest.fixture
def test_cities():
    """Load a few test cities into the database."""
    cities = [
        ("NorthCity", 55.0, 21.0),
        ("SouthCity", 49.0, 21.0),
        ("EastCity", 52.0, 25.0),
        ("WestCity", 52.0, 17.0),
    ]
    with get_test_db() as conn:
        conn.executemany(
            "INSERT INTO cities (name, latitude, longitude) VALUES (?, ?, ?)",
            cities,
        )
        conn.commit()
    return cities


# ── Helper: create a flock with a report ──────────────────────────────────────

def _create_flock_with_report(flock_id, lat, lon, ts_iso):
    """Create a Flock row with a Report row."""
    with get_test_db() as conn:
        conn.execute("INSERT INTO flocks (id) VALUES (?)", (flock_id,))
        conn.execute(
            "INSERT INTO reports (id, flock_id, latitude, longitude, timestamp) VALUES (?, ?, ?, ?, ?)",
            (flock_id + "_r1", flock_id, lat, lon, ts_iso),
        )
        conn.commit()


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
    _create_flock_with_report("old_flock", 52.0, 21.0, old_ts.isoformat())
    flock_id, is_new = identify_or_create_flock(52.0, 21.0, now)
    assert is_new is True
    assert flock_id != "old_flock"


def test_identify_flock_within_vmax():
    """New report within Vmax * time_delta should match existing flock."""
    now = datetime.now(timezone.utc)
    one_hour_ago = now - timedelta(hours=1)
    _create_flock_with_report("existing_flock", 52.0, 21.0, one_hour_ago.isoformat())
    # New report 50 km away, 1 hour later → dist 50 <= 100*1 → match
    flock_id, is_new = identify_or_create_flock(52.45, 21.0, now)
    assert is_new is False
    assert flock_id == "existing_flock"


def test_identify_flock_exceeds_vmax():
    """New report too far for the time window → new flock."""
    now = datetime.now(timezone.utc)
    two_hours_ago = now - timedelta(hours=2)
    _create_flock_with_report("far_flock", 52.0, 21.0, two_hours_ago.isoformat())
    # 500 km away in 2h → 250 km/h > Vmax 100 → new flock
    flock_id, is_new = identify_or_create_flock(56.5, 21.0, now)
    assert is_new is True
    assert flock_id != "far_flock"


def test_identify_closest_flock():
    """Two flocks in range → pick the closest one."""
    now = datetime.now(timezone.utc)
    one_hour_ago = now - timedelta(hours=1)
    _create_flock_with_report("flock_a", 52.09, 21.0, one_hour_ago.isoformat())
    _create_flock_with_report("flock_b", 52.27, 21.0, one_hour_ago.isoformat())
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
    with get_test_db() as conn:
        cursor = conn.execute(
            "SELECT COUNT(*) FROM reports WHERE flock_id = ?",
            (flock_id,),
        )
        assert cursor.fetchone()[0] == 2

        # Coordinator exists
        cursor = conn.execute(
            "SELECT COUNT(*) FROM flock_coordinators WHERE flock_id = ?",
            (flock_id,),
        )
        assert cursor.fetchone()[0] == 1


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
    bearing = 0.0
    result = predict_cities(52.0, 21.0, bearing)
    assert len(result) > 0
    assert result[0][0] == "NorthCity"


def test_predict_cities_no_city_in_tolerance():
    """If no city is within bearing tolerance, return empty list."""
    bearing = 45.0
    result = predict_cities(52.0, 21.0, bearing)
    assert isinstance(result, list)


def test_predict_cities_returns_multiple(test_cities):
    """Multiple cities in the same bearing sector should all be returned."""
    bearing = 0.0
    result = predict_cities(52.0, 21.0, bearing)
    for i in range(len(result) - 1):
        assert result[i][1] <= result[i + 1][1]


# ── Coordinator tests ─────────────────────────────────────────────────────────

def test_get_coordinators_for_flock():
    now = datetime.now(timezone.utc)
    flock_id, _ = identify_or_create_flock(52.0, 21.0, now)
    add_report_and_get_flock_info(flock_id, 52.0, 21.0, now, "coord@example.com")

    coords = get_coordinators_for_flock(flock_id)
    assert "coord@example.com" in coords
