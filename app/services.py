"""Business logic for BirdTracker — flock identification, report management, city prediction."""

import uuid
from datetime import datetime, timezone, timedelta

from .config import settings
from .utils import haversine_distance, calculate_bearing, angle_difference
from .sqlite_client import get_db


# ── Flock identification ───────────────────────────────────────────────────────

def identify_or_create_flock(
    lat: float, lon: float, timestamp: datetime
) -> tuple[str, bool]:
    """Identify an existing flock or create a new one.

    Algorithm:
      1. Find all reports whose timestamp is within
         ``SILENCE_WINDOW_HOURS`` of *timestamp*.
      2. For each candidate compute the distance from the candidate's
         last point to the new coordinates.
      3. Keep only candidates where ``dist <= V_MAX_KMH * hours_elapsed``.
      4. Pick the closest candidate.
      5. If no candidate survives → create a new flock.

    Returns ``(flock_id, is_new)``.
    """
    silence_hours = settings.silence_window_hours
    v_max = settings.v_max_kmh

    with get_db() as conn:
        # Find last report timestamps for all flocks within silence window
        silence_cutoff = (timestamp - timedelta(hours=silence_hours)).isoformat()
        cursor = conn.execute(
            """
            SELECT flock_id, latitude, longitude, timestamp
            FROM reports
            WHERE timestamp >= ?
            ORDER BY timestamp DESC
            """,
            (silence_cutoff,),
        )

        candidates: list[dict] = []
        for row in cursor:
            flock_id, last_lat, last_lon, last_ts_str = row
            last_ts = datetime.fromisoformat(last_ts_str)
            hours_elapsed = (timestamp - last_ts).total_seconds() / 3600
            dist = haversine_distance(lat, lon, last_lat, last_lon)
            max_allowed = v_max * hours_elapsed
            if dist <= max_allowed:
                candidates.append(
                    {
                        "flock_id": flock_id,
                        "dist": dist,
                        "last_ts": last_ts,
                        "lat": last_lat,
                        "lon": last_lon,
                    }
                )

        if candidates:
            # Pick closest
            candidates.sort(key=lambda c: c["dist"])
            best = candidates[0]
            return best["flock_id"], False

    # No candidate → create new flock + initial report
    flock_id = str(uuid.uuid4())
    report_id = str(uuid.uuid4())
    with get_db() as conn:
        conn.execute(
            "INSERT INTO flocks (id) VALUES (?)",
            (flock_id,),
        )
        conn.execute(
            """
            INSERT INTO reports (id, flock_id, latitude, longitude, timestamp)
            VALUES (?, ?, ?, ?, ?)
            """,
            (report_id, flock_id, lat, lon, timestamp.isoformat()),
        )
    return flock_id, True


# ── Adding a report ────────────────────────────────────────────────────────────

def add_report_and_get_flock_info(
    flock_id: str,
    lat: float,
    lon: float,
    timestamp: datetime,
    coordinator_email: str,
    skip_create: bool = False,
) -> tuple[str, list[dict]]:
    """Add a new Report to *flock_id*, update LAST_REPORT, create Coordinator.

    If *skip_create* is True, the flock already has an initial report
    (created by ``identify_or_create_flock``) and we only need to update
    LAST_REPORT and the coordinator.

    Returns ``(report_id, last_2_points)`` where *last_2_points* is a list of
    dicts with keys ``location`` (tuple of lat, lon) and ``timestamp`` (datetime).
    """
    if skip_create:
        # The initial report was already created by identify_or_create_flock
        # Just update its coordinates and timestamp
        with get_db() as conn:
            conn.execute(
                """
                UPDATE reports
                SET latitude = ?, longitude = ?, timestamp = ?
                WHERE flock_id = ?
                AND timestamp = (
                    SELECT MAX(timestamp) FROM reports WHERE flock_id = ?
                )
                """,
                (lat, lon, timestamp.isoformat(), flock_id, flock_id),
            )
            # Get the report id of the existing report
            cursor = conn.execute(
                "SELECT id FROM reports WHERE flock_id = ? ORDER BY timestamp DESC LIMIT 1",
                (flock_id,),
            )
            report_id = cursor.fetchone()[0]
    else:
        report_id = str(uuid.uuid4())
        # Create Report row and link to Flock
        with get_db() as conn:
            conn.execute(
                """
                INSERT INTO reports (id, flock_id, latitude, longitude, timestamp)
                VALUES (?, ?, ?, ?, ?)
                """,
                (report_id, flock_id, lat, lon, timestamp.isoformat()),
            )

    # Create / link Coordinator
    with get_db() as conn:
        conn.execute(
            "INSERT OR IGNORE INTO coordinators (email) VALUES (?)",
            (coordinator_email,),
        )
        conn.execute(
            "INSERT OR IGNORE INTO flock_coordinators (flock_id, coordinator_email) VALUES (?, ?)",
            (flock_id, coordinator_email),
        )

    # Fetch last 2 reports for this flock
    with get_db() as conn:
        cursor = conn.execute(
            """
            SELECT latitude, longitude, timestamp
            FROM reports
            WHERE flock_id = ?
            ORDER BY timestamp DESC
            LIMIT 2
            """,
            (flock_id,),
        )
        last_points = [
            {"location": (row[0], row[1]), "timestamp": datetime.fromisoformat(row[2])}
            for row in cursor
        ]

    return report_id, last_points


# ── City prediction ────────────────────────────────────────────────────────────

def predict_cities(lat: float, lon: float, bearing: float) -> list[tuple[str, float]]:
    """Predict which cities the flock is heading toward.

    Filters cities within ``BEARING_TOLERANCE_DEG`` of *bearing*, then returns
    **all** matching cities sorted by distance as ``[(city_name, distance_km), ...]``.
    """
    tolerance = settings.bearing_tolerance_deg

    with get_db() as conn:
        cursor = conn.execute(
            "SELECT name, latitude, longitude FROM cities"
        )

        candidates: list[tuple[str, float]] = []
        for row in cursor:
            name, city_lat, city_lon = row
            city_bearing = calculate_bearing(lat, lon, city_lat, city_lon)
            diff = angle_difference(bearing, city_bearing)
            if diff <= tolerance:
                dist = haversine_distance(lat, lon, city_lat, city_lon)
                candidates.append((name, dist))

        candidates.sort(key=lambda x: x[1])
        return candidates


# ── Fetch coordinators for a flock ─────────────────────────────────────────────

def get_coordinators_for_flock(flock_id: str) -> list[str]:
    """Return list of coordinator emails linked to *flock_id*."""
    with get_db() as conn:
        cursor = conn.execute(
            "SELECT coordinator_email FROM flock_coordinators WHERE flock_id = ?",
            (flock_id,),
        )
        return [row[0] for row in cursor]


# ── Report counting ────────────────────────────────────────────────────────────

def count_reports_for_flock(flock_id: str) -> int:
    """Return the total number of reports for *flock_id*."""
    with get_db() as conn:
        cursor = conn.execute(
            "SELECT COUNT(*) FROM reports WHERE flock_id = ?",
            (flock_id,),
        )
        return cursor.fetchone()[0]


# ── Nearest city lookup ────────────────────────────────────────────────────────

def get_nearest_city(lat: float, lon: float) -> str | None:
    """Return the name of the nearest city to the given coordinates, or ``None``."""
    with get_db() as conn:
        cursor = conn.execute(
            "SELECT name, latitude, longitude FROM cities"
        )

        best_name: str | None = None
        best_dist: float | None = None
        for row in cursor:
            name, city_lat, city_lon = row
            dist = haversine_distance(lat, lon, city_lat, city_lon)
            if best_dist is None or dist < best_dist:
                best_dist = dist
                best_name = name

    return best_name


# ── Notification decision ──────────────────────────────────────────────────────

def should_send_notification(
    flock_id: str,
    is_new_flock: bool,
    report_count: int,
    current_city: str | None,
    last_report_city: str | None,
) -> bool:
    """Decide whether a notification should be sent for the current report.

    Rules (any one triggers a notification):
      1. **New flock** — always notify on flock creation.
      2. **Cumulative thresholds** — notify when report_count hits
         level1, level2, level3, or any multiple of level4 thereafter.
         E.g. with defaults: 1, 5, 25, 100, 200, 300, …
      3. **New town** — notify when the nearest city changes compared
         to the previous report's nearest city.
    """
    if is_new_flock:
        return True

    thresholds = _get_notification_thresholds()
    if _hits_threshold(report_count, thresholds):
        return True

    if current_city is not None and last_report_city is not None:
        if current_city != last_report_city:
            return True

    return False


def _get_notification_thresholds() -> tuple[int, int, int, int]:
    """Return the four notification threshold levels."""
    return (
        settings.notification_threshold_level1,
        settings.notification_threshold_level2,
        settings.notification_threshold_level3,
        settings.notification_threshold_level4,
    )


def _hits_threshold(report_count: int, thresholds: tuple[int, int, int, int]) -> bool:
    """Check whether *report_count* hits any cumulative threshold.

    The sequence is: level1, level2, level3, level4, level4*2, level4*3, …
    """
    level1, level2, level3, level4 = thresholds

    if report_count == level1:
        return True
    if report_count == level2:
        return True
    if report_count == level3:
        return True

    if report_count >= level4 and report_count % level4 == 0:
        return True

    return False
