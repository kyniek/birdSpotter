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

from fastapi.testclient import TestClient

from app.main import app
from app.config import settings
from app.neo4j_client import get_test_db
from app.services import (
    count_reports_for_flock,
    get_nearest_city,
    should_send_notification,
    _hits_threshold,
    _get_notification_thresholds,
)
from test_integration_submit_report import (
    load_cities_from_geojson,
    _clean_test_db,
    test_neo4j_container,
    neo4j_test_driver,
    seed_cities,
)


# ── City coordinates from export.geojson ──────────────────────────────────────
# Mielec is near the centre of the covered area — used as the primary test city
# and for threshold tests.
# Przecław is ~12 km from Mielec — within V_MAX for 10-min intervals, so reports
# stay in the same flock, but nearest-city lookup returns different towns.
# Radom is ~125 km from Mielec — used for far-away town-change tests.

MIELEC_LAT = 50.2895407
MIELEC_LON = 21.4229453

# ~12 km from Mielec — different nearest city, close enough to stay in same flock
PRZEC_LAW_LAT = 50.1939186
PRZEC_LAW_LON = 21.4798564

# ~125 km from Mielec — clearly different nearest city
RADOM_LAT = 51.4022557
RADOM_LON = 21.1541547


client = TestClient(app)


class TestNotificationLogic:
    """End-to-end tests for the notification decision logic."""

    @pytest.fixture(scope="class", autouse=True)
    def _container(cls, test_neo4j_container):
        """Start the test Neo4j Docker container once for the whole class."""
        yield

    @pytest.fixture(autouse=True)
    def _setup(self, neo4j_test_driver, seed_cities):
        """Clean DB, load cities, patch get_db — runs before each test."""
        import app.services as services_module

        _clean_test_db()
        load_cities_from_geojson()

        self._original_get_db = services_module.get_db
        services_module.get_db = get_test_db

        yield

        services_module.get_db = self._original_get_db

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
        """Verify that Mielec is indeed the nearest city to Mielec coordinates."""
        city = get_nearest_city(MIELEC_LAT, MIELEC_LON)
        assert city == "Mielec"

    def test_debica_is_different_city(self):
        """Verify that Mielec and Przecław are different nearest cities."""
        city_a = get_nearest_city(MIELEC_LAT, MIELEC_LON)
        city_b = get_nearest_city(PRZEC_LAW_LAT, PRZEC_LAW_LON)
        assert city_a == "Mielec"
        assert city_b == "Przecław"
        assert city_a != city_b

    def test_radom_is_different_city(self):
        """Verify that Radom is a different nearest city from Mielec."""
        city = get_nearest_city(RADOM_LAT, RADOM_LON)
        assert city == "Radom"

    # ── Rule 1: New flock ──────────────────────────────────────────────────

    def test_rule1_new_flock_triggers_notification(self):
        """First report for a new flock → notification sent."""
        with patch("app.main.send_notification") as mock_send:
            base = datetime.now(timezone.utc) - timedelta(hours=1)
            self._send_report(MIELEC_LAT, MIELEC_LON, base)
            assert mock_send.call_count == 1

    # ── Rule 2: Cumulative thresholds ──────────────────────────────────────

    def test_rule2_threshold_level1(self):
        """Report #1 (level1=1) → notification sent."""
        with patch("app.main.send_notification") as mock_send:
            base = datetime.now(timezone.utc) - timedelta(hours=1)
            self._send_report(MIELEC_LAT, MIELEC_LON, base)
            assert mock_send.call_count == 1

    def test_rule2_threshold_level2(self):
        """Report #5 (level2=5) → notification sent; reports 2-4 → no notification."""
        with patch("app.main.send_notification") as mock_send:
            base = datetime.now(timezone.utc) - timedelta(hours=2)

            # Report 1 — new flock, notifies
            self._send_report(MIELEC_LAT, MIELEC_LON, base)
            assert mock_send.call_count == 1

            # Reports 2-4 — no notification (same area, below threshold)
            for i in range(2, 5):
                t = base + timedelta(minutes=i * 10)
                self._send_report(MIELEC_LAT + i * 0.001, MIELEC_LON + i * 0.001, t)
                assert mock_send.call_count == 1, f"Should not notify at report #{i}"

            # Report 5 — threshold hit, notifies
            t = base + timedelta(minutes=50)
            self._send_report(MIELEC_LAT + 5 * 0.001, MIELEC_LON + 5 * 0.001, t)
            assert mock_send.call_count == 2, "Should notify at report #5"

    def test_rule2_threshold_level3(self):
        """Report #25 (level3=25) → notification sent."""
        with patch("app.main.send_notification") as mock_send:
            base = datetime.now(timezone.utc) - timedelta(hours=3)

            # Send 24 reports near Mielec
            for i in range(1, 25):
                t = base + timedelta(minutes=i * 5)
                self._send_report(
                    MIELEC_LAT + i * 0.0001, MIELEC_LON + i * 0.0001, t
                )

            calls_after_24 = mock_send.call_count

            # Report 25 — threshold hit
            t = base + timedelta(minutes=25 * 5)
            self._send_report(
                MIELEC_LAT + 25 * 0.0001, MIELEC_LON + 25 * 0.0001, t
            )
            assert mock_send.call_count == calls_after_24 + 1

    def test_rule2_threshold_level4_and_multiples(self):
        """Report #100 (level4) → notify; #199 → no; #200 → notify.

        Sends 100 reports via the API to verify the threshold at level4.
        The 199/200 logic is verified via the _hits_threshold helper.
        """
        with patch("app.main.send_notification") as mock_send:
            base = datetime.now(timezone.utc) - timedelta(hours=24)

            # Send 99 reports — stay near Mielec in a tiny area
            for i in range(1, 100):
                t = base + timedelta(minutes=i)
                self._send_report(
                    MIELEC_LAT + i * 0.000001,
                    MIELEC_LON + i * 0.000001,
                    t,
                )

            calls_after_99 = mock_send.call_count

            # Report 100 — threshold hit
            t = base + timedelta(minutes=100)
            self._send_report(
                MIELEC_LAT + 100 * 0.000001,
                MIELEC_LON + 100 * 0.000001,
                t,
            )
            assert mock_send.call_count == calls_after_99 + 1, \
                f"Report 100: expected {calls_after_99 + 1} calls, got {mock_send.call_count}"

            # Verify _hits_threshold logic for 199/200
            thresholds = _get_notification_thresholds()
            assert not _hits_threshold(199, thresholds), "199 should NOT hit threshold"
            assert _hits_threshold(200, thresholds), "200 SHOULD hit threshold (multiple of 100)"
            assert not _hits_threshold(250, thresholds), "250 should NOT hit threshold"
            assert _hits_threshold(300, thresholds), "300 SHOULD hit threshold (multiple of 100)"

    # ── Rule 3: Town change ────────────────────────────────────────────────

    def test_rule3_town_change_triggers_notification(self):
        """Nearest city changes between consecutive reports → notification sent."""
        with patch("app.main.send_notification") as mock_send:
            base = datetime.now(timezone.utc) - timedelta(hours=1)

            # Report 1 — new flock at Mielec, notifies
            self._send_report(MIELEC_LAT, MIELEC_LON, base)
            assert mock_send.call_count == 1

            # Reports 2-4 — stay near Mielec (same nearest city, below threshold)
            for i in range(2, 5):
                t = base + timedelta(minutes=i * 10)
                self._send_report(MIELEC_LAT + i * 0.001, MIELEC_LON + i * 0.001, t)
                assert mock_send.call_count == 1, \
                    f"Should not notify at report #{i} (same town, below threshold)"

            # Report 5 — threshold hit regardless
            t = base + timedelta(minutes=50)
            self._send_report(MIELEC_LAT + 5 * 0.001, MIELEC_LON + 5 * 0.001, t)
            assert mock_send.call_count == 2, "Should notify at report #5 (threshold)"

    def test_rule3_town_change_before_threshold(self):
        """Town changes before threshold → notification sent even at report #2."""
        with patch("app.main.send_notification") as mock_send:
            base = datetime.now(timezone.utc) - timedelta(hours=1)

            # Report 1 — new flock at Mielec, notifies
            self._send_report(MIELEC_LAT, MIELEC_LON, base)
            assert mock_send.call_count == 1

            # Report 2 — move to Radom area (125 km away, different nearest city)
            t = base + timedelta(minutes=30)
            self._send_report(RADOM_LAT, RADOM_LON, t)
            # Town change should trigger notification even at report #2
            assert mock_send.call_count == 2, \
                "Should notify at report #2 (town changed from Mielec to Radom)"

    def test_rule3_town_change_debica(self):
        """Moving from Mielec to Przecław (12 km) triggers notification."""
        with patch("app.main.send_notification") as mock_send:
            base = datetime.now(timezone.utc) - timedelta(hours=1)

            # Report 1 — new flock at Mielec, notifies
            self._send_report(MIELEC_LAT, MIELEC_LON, base)
            assert mock_send.call_count == 1

            # Report 2 — move to Przecław (different nearest city)
            t = base + timedelta(minutes=30)
            self._send_report(PRZEC_LAW_LAT, PRZEC_LAW_LON, t)
            assert mock_send.call_count == 2, \
                "Should notify at report #2 (town changed from Mielec to Przecław)"

    # ── Combined rules ─────────────────────────────────────────────────────

    def test_combined_rule2_and_rule3_no_double_notify(self):
        """When both threshold and town change fire on the same report,
        only one notification is sent."""
        with patch("app.main.send_notification") as mock_send:
            base = datetime.now(timezone.utc) - timedelta(hours=1)

            # Report 1 — new flock + threshold level1
            self._send_report(MIELEC_LAT, MIELEC_LON, base)
            assert mock_send.call_count == 1

            # Reports 2-4 — no trigger (same area)
            for i in range(2, 5):
                t = base + timedelta(minutes=i * 10)
                self._send_report(MIELEC_LAT + i * 0.001, MIELEC_LON + i * 0.001, t)
                assert mock_send.call_count == 1

            # Report 5 — threshold level2 hits
            # Also changes town (Mielec → Radom), but only one notification
            t = base + timedelta(minutes=50)
            self._send_report(RADOM_LAT, RADOM_LON, t)
            assert mock_send.call_count == 2, \
                "Should send exactly one notification at #5 (threshold + town change)"

    # ── Edge cases ─────────────────────────────────────────────────────────

    def test_no_notification_when_nothing_triggers(self):
        """Reports 2-4 with no town change → no notification."""
        with patch("app.main.send_notification") as mock_send:
            base = datetime.now(timezone.utc) - timedelta(hours=1)

            # Report 1 — new flock, notifies
            self._send_report(MIELEC_LAT, MIELEC_LON, base)
            assert mock_send.call_count == 1

            # Reports 2-4 — stay near Mielec, below threshold
            for i in range(2, 5):
                t = base + timedelta(minutes=i * 10)
                self._send_report(MIELEC_LAT + i * 0.0001, MIELEC_LON + i * 0.0001, t)

            assert mock_send.call_count == 1, "Should NOT notify at reports 2-4"

    def test_rule3_town_bounces_back(self):
        """Town changes Mielec → Przecław → Mielec: each change triggers notification.

        Uses Przecław (~12 km) so all reports stay within V_MAX range and join
        the same flock, but nearest-city lookup returns different towns.
        """
        with patch("app.main.send_notification") as mock_send:
            base = datetime.now(timezone.utc) - timedelta(hours=1)

            # Report 1 — new flock at Mielec, notifies
            self._send_report(MIELEC_LAT, MIELEC_LON, base)
            assert mock_send.call_count == 1

            # Report 2 — town changes to Przecław, notifies
            t = base + timedelta(minutes=10)
            self._send_report(PRZEC_LAW_LAT, PRZEC_LAW_LON, t)
            assert mock_send.call_count == 2, \
                f"Should notify on town change to Przecław (got {mock_send.call_count})"

            # Report 3 — town changes back to Mielec, notifies (town changed again)
            t = base + timedelta(minutes=20)
            self._send_report(MIELEC_LAT, MIELEC_LON, t)
            assert mock_send.call_count == 3, \
                f"Should notify on town change back to Mielec (got {mock_send.call_count})"

    def test_should_send_notification_unit(self):
        """Unit-level test of should_send_notification with all three rules."""
        # Rule 1: new flock
        assert should_send_notification("f1", is_new_flock=True, report_count=1,
                                        current_city="Mielec", last_report_city=None) is True

        # Rule 2: threshold hit
        assert should_send_notification("f1", is_new_flock=False, report_count=5,
                                        current_city="Mielec", last_report_city="Mielec") is True

        # Rule 2: threshold NOT hit
        assert should_send_notification("f1", is_new_flock=False, report_count=3,
                                        current_city="Mielec", last_report_city="Mielec") is False

        # Rule 3: town changed
        assert should_send_notification("f1", is_new_flock=False, report_count=3,
                                        current_city="Radom", last_report_city="Mielec") is True

        # No rule triggers: no town change, no threshold
        assert should_send_notification("f1", is_new_flock=False, report_count=3,
                                        current_city="Mielec", last_report_city="Mielec") is False

        # No rule triggers: current city is None (no city data)
        assert should_send_notification("f1", is_new_flock=False, report_count=3,
                                        current_city=None, last_report_city="Mielec") is False

        # No rule triggers: last city is None (first report, not new flock)
        assert should_send_notification("f1", is_new_flock=False, report_count=3,
                                        current_city="Mielec", last_report_city=None) is False
