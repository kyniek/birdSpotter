"""Integration tests for notification logic in submit_report.

Tests the three notification rules:
  1. New flock → always notify
  2. Cumulative thresholds (1, 5, 25, 100, 200, …) → notify
  3. Nearest town changes between consecutive reports → notify

City data is loaded from export.geojson (via load_cities_from_geojson).
Mielec (50.2895, 21.4229) is used as the central reference city.
"""

import pytest
from datetime import datetime, timezone, timedelta
from unittest.mock import patch
from pathlib import Path

from fastapi.testclient import TestClient

from app.main import app
from app.config import settings
from app.sqlite_client import get_test_db
from app.services import (
    count_reports_for_flock,
    get_nearest_city,
    should_send_notification,
    _hits_threshold,
    _get_notification_thresholds,
)


# ── City coordinates from export.geojson ──────────────────────────────────────
MIELEC_LAT = 50.2895407
MIELEC_LON = 21.4229453

PRZEC_LAW_LAT = 50.1939186
PRZEC_LAW_LON = 21.4798564

RADOM_LAT = 51.4022557
RADOM_LON = 21.1541547


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


client = TestClient(app)


class TestNotificationLogic:
    """End-to-end tests for the notification decision logic."""

    @pytest.fixture(autouse=True)
    def _setup(self):
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

    def _send_report(self, lat, lon, timestamp, email="alice@example.com"):
        """Helper to POST a report and return the JSON response."""
        resp = client.post(
            "/api/report",
            json={
                "latitude": lat,
                "longitude": lon,
                "timestamp": timestamp.isoformat(),
                "coordinator_email": email,
            },
        )
        if resp.status_code != 200:
            raise AssertionError(
                f"Report failed with status {resp.status_code}: {resp.text}"
            )
        return resp.json()

    # ── Helpers ──────────────────────────────────────────────────────────────

    def test_nearest_city_is_mielec(self):
        city = get_nearest_city(MIELEC_LAT, MIELEC_LON)
        assert city == "Mielec"

    def test_debica_is_different_city(self):
        city_a = get_nearest_city(MIELEC_LAT, MIELEC_LON)
        city_b = get_nearest_city(PRZEC_LAW_LAT, PRZEC_LAW_LON)
        assert city_a == "Mielec"
        assert city_b == "Przecław"
        assert city_a != city_b

    def test_radom_is_different_city(self):
        city = get_nearest_city(RADOM_LAT, RADOM_LON)
        assert city == "Radom"

    # ── Rule 1: New flock ──────────────────────────────────────────────────

    def test_rule1_new_flock_triggers_notification(self):
        with patch("app.main.send_notification") as mock_send:
            base = datetime.now(timezone.utc) - timedelta(hours=1)
            self._send_report(MIELEC_LAT, MIELEC_LON, base)
            assert mock_send.call_count == 1

    # ── Rule 2: Cumulative thresholds ──────────────────────────────────────

    def test_rule2_threshold_level1(self):
        with patch("app.main.send_notification") as mock_send:
            base = datetime.now(timezone.utc) - timedelta(hours=1)
            self._send_report(MIELEC_LAT, MIELEC_LON, base)
            assert mock_send.call_count == 1

    def test_rule2_threshold_level2(self):
        with patch("app.main.send_notification") as mock_send:
            base = datetime.now(timezone.utc) - timedelta(hours=2)

            self._send_report(MIELEC_LAT, MIELEC_LON, base)
            assert mock_send.call_count == 1

            for i in range(2, 5):
                t = base + timedelta(minutes=i * 10)
                self._send_report(MIELEC_LAT + i * 0.001, MIELEC_LON + i * 0.001, t)
                assert mock_send.call_count == 1, f"Should not notify at report #{i}"

            t = base + timedelta(minutes=50)
            self._send_report(MIELEC_LAT + 5 * 0.001, MIELEC_LON + 5 * 0.001, t)
            assert mock_send.call_count == 2, "Should notify at report #5"

    def test_rule2_threshold_level3(self):
        with patch("app.main.send_notification") as mock_send:
            base = datetime.now(timezone.utc) - timedelta(hours=3)

            for i in range(1, 25):
                t = base + timedelta(minutes=i * 5)
                self._send_report(
                    MIELEC_LAT + i * 0.0001, MIELEC_LON + i * 0.0001, t
                )

            calls_after_24 = mock_send.call_count

            t = base + timedelta(minutes=25 * 5)
            self._send_report(
                MIELEC_LAT + 25 * 0.0001, MIELEC_LON + 25 * 0.0001, t
            )
            assert mock_send.call_count == calls_after_24 + 1

    def test_rule2_threshold_level4_and_multiples(self):
        with patch("app.main.send_notification") as mock_send:
            base = datetime.now(timezone.utc) - timedelta(hours=24)

            for i in range(1, 100):
                t = base + timedelta(minutes=i)
                self._send_report(
                    MIELEC_LAT + i * 0.000001,
                    MIELEC_LON + i * 0.000001,
                    t,
                )

            calls_after_99 = mock_send.call_count

            t = base + timedelta(minutes=100)
            self._send_report(
                MIELEC_LAT + 100 * 0.000001,
                MIELEC_LON + 100 * 0.000001,
                t,
            )
            assert mock_send.call_count == calls_after_99 + 1, \
                f"Report 100: expected {calls_after_99 + 1} calls, got {mock_send.call_count}"

            thresholds = _get_notification_thresholds()
            assert not _hits_threshold(199, thresholds), "199 should NOT hit threshold"
            assert _hits_threshold(200, thresholds), "200 SHOULD hit threshold (multiple of 100)"
            assert not _hits_threshold(250, thresholds), "250 should NOT hit threshold"
            assert _hits_threshold(300, thresholds), "300 SHOULD hit threshold (multiple of 100)"

    # ── Rule 3: Town change ────────────────────────────────────────────────

    def test_rule3_town_change_triggers_notification(self):
        with patch("app.main.send_notification") as mock_send:
            base = datetime.now(timezone.utc) - timedelta(hours=1)

            self._send_report(MIELEC_LAT, MIELEC_LON, base)
            assert mock_send.call_count == 1

            for i in range(2, 5):
                t = base + timedelta(minutes=i * 10)
                self._send_report(MIELEC_LAT + i * 0.001, MIELEC_LON + i * 0.001, t)
                assert mock_send.call_count == 1, \
                    f"Should not notify at report #{i} (same town, below threshold)"

            t = base + timedelta(minutes=50)
            self._send_report(MIELEC_LAT + 5 * 0.001, MIELEC_LON + 5 * 0.001, t)
            assert mock_send.call_count == 2, "Should notify at report #5 (threshold)"

    def test_rule3_town_change_before_threshold(self):
        with patch("app.main.send_notification") as mock_send:
            base = datetime.now(timezone.utc) - timedelta(hours=1)

            self._send_report(MIELEC_LAT, MIELEC_LON, base)
            assert mock_send.call_count == 1

            t = base + timedelta(minutes=30)
            self._send_report(RADOM_LAT, RADOM_LON, t)
            assert mock_send.call_count == 2, \
                "Should notify at report #2 (town changed from Mielec to Radom)"

    def test_rule3_town_change_debica(self):
        with patch("app.main.send_notification") as mock_send:
            base = datetime.now(timezone.utc) - timedelta(hours=1)

            self._send_report(MIELEC_LAT, MIELEC_LON, base)
            assert mock_send.call_count == 1

            t = base + timedelta(minutes=30)
            self._send_report(PRZEC_LAW_LAT, PRZEC_LAW_LON, t)
            assert mock_send.call_count == 2, \
                "Should notify at report #2 (town changed from Mielec to Przecław)"

    # ── Combined rules ─────────────────────────────────────────────────────

    def test_combined_rule2_and_rule3_no_double_notify(self):
        with patch("app.main.send_notification") as mock_send:
            base = datetime.now(timezone.utc) - timedelta(hours=1)

            self._send_report(MIELEC_LAT, MIELEC_LON, base)
            assert mock_send.call_count == 1

            for i in range(2, 5):
                t = base + timedelta(minutes=i * 10)
                self._send_report(MIELEC_LAT + i * 0.001, MIELEC_LON + i * 0.001, t)
                assert mock_send.call_count == 1

            t = base + timedelta(minutes=50)
            self._send_report(RADOM_LAT, RADOM_LON, t)
            assert mock_send.call_count == 2, \
                "Should send exactly one notification at #5 (threshold + town change)"

    # ── Edge cases ─────────────────────────────────────────────────────────

    def test_no_notification_when_nothing_triggers(self):
        with patch("app.main.send_notification") as mock_send:
            base = datetime.now(timezone.utc) - timedelta(hours=1)

            self._send_report(MIELEC_LAT, MIELEC_LON, base)
            assert mock_send.call_count == 1

            for i in range(2, 5):
                t = base + timedelta(minutes=i * 10)
                self._send_report(MIELEC_LAT + i * 0.0001, MIELEC_LON + i * 0.0001, t)

            assert mock_send.call_count == 1, "Should NOT notify at reports 2-4"

    def test_rule3_town_bounces_back(self):
        with patch("app.main.send_notification") as mock_send:
            base = datetime.now(timezone.utc) - timedelta(hours=1)

            self._send_report(MIELEC_LAT, MIELEC_LON, base)
            assert mock_send.call_count == 1

            t = base + timedelta(minutes=10)
            self._send_report(PRZEC_LAW_LAT, PRZEC_LAW_LON, t)
            assert mock_send.call_count == 2, \
                f"Should notify on town change to Przecław (got {mock_send.call_count})"

            t = base + timedelta(minutes=20)
            self._send_report(MIELEC_LAT, MIELEC_LON, t)
            assert mock_send.call_count == 3, \
                f"Should notify on town change back to Mielec (got {mock_send.call_count})"

    def test_should_send_notification_unit(self):
        assert should_send_notification("f1", is_new_flock=True, report_count=1,
                                        current_city="Mielec", last_report_city=None) is True

        assert should_send_notification("f1", is_new_flock=False, report_count=5,
                                        current_city="Mielec", last_report_city="Mielec") is True

        assert should_send_notification("f1", is_new_flock=False, report_count=3,
                                        current_city="Mielec", last_report_city="Mielec") is False

        assert should_send_notification("f1", is_new_flock=False, report_count=3,
                                        current_city="Radom", last_report_city="Mielec") is True

        assert should_send_notification("f1", is_new_flock=False, report_count=3,
                                        current_city="Mielec", last_report_city="Mielec") is False

        assert should_send_notification("f1", is_new_flock=False, report_count=3,
                                        current_city=None, last_report_city="Mielec") is False

        assert should_send_notification("f1", is_new_flock=False, report_count=3,
                                        current_city="Mielec", last_report_city=None) is False
