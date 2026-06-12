import uuid
from datetime import datetime, timezone, timedelta

from neo4j import GraphDatabase

from .config import settings
from .utils import haversine_distance, calculate_bearing, angle_difference
from .neo4j_client import get_db


# ── Flock identification ───────────────────────────────────────────────────────

def identify_or_create_flock(
    lat: float, lon: float, timestamp: datetime
) -> tuple[str, bool]:
    """Identify an existing flock or create a new one.

    Algorithm:
      1. Find all Flock nodes whose LAST_REPORT timestamp is within
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

    with get_db() as session:
        # Find last report timestamps for all flocks
        result = session.run(
            """
            MATCH (f:Flock)-[:LAST_REPORT]->(r:Report)
            WHERE r.timestamp >= datetime($ts) - duration({hours: $silence})
            RETURN f.id AS flock_id,
                   r.location.y AS lat,
                   r.location.x AS lon,
                   r.timestamp AS ts
            ORDER BY r.timestamp DESC
            """,
            ts=timestamp.isoformat(),
            silence=silence_hours,
        )

        candidates: list[dict] = []
        for record in result:
            last_ts = record["ts"].to_native()  # datetime
            hours_elapsed = (timestamp - last_ts).total_seconds() / 3600
            dist = haversine_distance(
                lat, lon, record["lat"], record["lon"]
            )
            max_allowed = v_max * hours_elapsed
            if dist <= max_allowed:
                candidates.append(
                    {
                        "flock_id": record["flock_id"],
                        "dist": dist,
                        "last_ts": last_ts,
                        "lat": record["lat"],
                        "lon": record["lon"],
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
    with get_db() as session:
        session.run(
            """
            CREATE (f:Flock {id: $flock_id})
            CREATE (r:Report {
                id: $report_id,
                location: point({latitude: $lat, longitude: $lon}),
                timestamp: datetime($ts)
            })
            CREATE (f)-[:HAS_REPORT]->(r)
            CREATE (f)-[:LAST_REPORT]->(r)
            """,
            flock_id=flock_id,
            report_id=report_id,
            lat=lat,
            lon=lon,
            ts=timestamp.isoformat(),
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
    dicts with keys ``location`` (Point) and ``timestamp`` (datetime).
    """

    with get_db() as session:
        if not skip_create:
            report_id = str(uuid.uuid4())
            # Create Report node and link to Flock
            session.run(
                """
                MATCH (f:Flock {id: $flock_id})
                CREATE (r:Report {
                    id: $report_id,
                    location: point({latitude: $lat, longitude: $lon}),
                    timestamp: datetime($ts)
                })
                CREATE (f)-[:HAS_REPORT]->(r)
                """,
                flock_id=flock_id,
                report_id=report_id,
                lat=lat,
                lon=lon,
                ts=timestamp.isoformat(),
            )
        else:
            # The initial report was already created by identify_or_create_flock
            # Just update its coordinates and timestamp
            session.run(
                """
                MATCH (f:Flock {id: $flock_id})-[:HAS_REPORT]->(r:Report)
                SET r.location = point({latitude: $lat, longitude: $lon}), r.timestamp = datetime($ts)
                """,
                flock_id=flock_id,
                lat=lat,
                lon=lon,
                ts=timestamp.isoformat(),
            )
            # Get the report id of the existing report
            result = session.run(
                "MATCH (f:Flock {id: $flock_id})-[:HAS_REPORT]->(r:Report) RETURN r.id AS rid",
                flock_id=flock_id,
            )
            report_id = list(result)[0]["rid"]

        # Update LAST_REPORT relationship (delete old, create new)
        session.run(
            """
            MATCH (f:Flock {id: $flock_id})-[rel:LAST_REPORT]->(old:Report)
            DELETE rel
            """,
            flock_id=flock_id,
        )
        session.run(
            """
            MATCH (f:Flock {id: $flock_id})-[:HAS_REPORT]->(new:Report)
            WHERE new.id = $report_id
            CREATE (f)-[:LAST_REPORT]->(new)
            """,
            flock_id=flock_id,
            report_id=report_id,
        )

        # Create / link Coordinator
        session.run(
            """
            MATCH (f:Flock {id: $flock_id})
            MERGE (c:Coordinator {email: $email})
            MERGE (f)-[:NOTIFIED_OF]->(c)
            """,
            flock_id=flock_id,
            email=coordinator_email,
        )

        # Fetch last 2 reports for this flock
        result = session.run(
            """
            MATCH (f:Flock {id: $flock_id})-[:HAS_REPORT]->(r:Report)
            RETURN r.location.y AS lat, r.location.x AS lon, r.timestamp AS ts
            ORDER BY r.timestamp DESC
            LIMIT 2
            """,
            flock_id=flock_id,
        )
        last_points = [
            {"location": (rec["lat"], rec["lon"]), "timestamp": rec["ts"].to_native()}
            for rec in result
        ]

    return report_id, last_points


# ── City prediction ────────────────────────────────────────────────────────────

def predict_cities(lat: float, lon: float, bearing: float) -> list[tuple[str, float]]:
    """Predict which cities the flock is heading toward.

    Filters cities within ``BEARING_TOLERANCE_DEG`` of *bearing*, then returns
    **all** matching cities sorted by distance as ``[(city_name, distance_km), ...]``.
    """
    tolerance = settings.bearing_tolerance_deg

    with get_db() as session:
        result = session.run(
            """
            MATCH (c:City)
            RETURN c.name AS name, c.location.y AS lat, c.location.x AS lon
            """
        )

        candidates: list[tuple[str, float]] = []
        for record in result:
            city_lat = record["lat"]
            city_lon = record["lon"]
            city_bearing = calculate_bearing(lat, lon, city_lat, city_lon)
            diff = angle_difference(bearing, city_bearing)
            if diff <= tolerance:
                dist = haversine_distance(lat, lon, city_lat, city_lon)
                candidates.append((record["name"], dist))

        candidates.sort(key=lambda x: x[1])
        return candidates


# ── Fetch coordinators for a flock ─────────────────────────────────────────────

def get_coordinators_for_flock(flock_id: str) -> list[str]:
    """Return list of coordinator emails linked to *flock_id*."""
    with get_db() as session:
        result = session.run(
            """
            MATCH (f:Flock {id: $flock_id})-[:NOTIFIED_OF]->(c:Coordinator)
            RETURN c.email AS email
            """,
            flock_id=flock_id,
        )
        return [rec["email"] for rec in result]


# ── Report counting ────────────────────────────────────────────────────────────

def count_reports_for_flock(flock_id: str) -> int:
    """Return the total number of reports for *flock_id*."""
    with get_db() as session:
        result = session.run(
            """
            MATCH (f:Flock {id: $flock_id})-[:HAS_REPORT]->(r:Report)
            RETURN count(r) AS cnt
            """,
            flock_id=flock_id,
        )
        return result.single()["cnt"]


# ── Nearest city lookup ────────────────────────────────────────────────────────

def get_nearest_city(lat: float, lon: float) -> str | None:
    """Return the name of the nearest city to the given coordinates, or ``None``."""
    tolerance = settings.bearing_tolerance_deg

    with get_db() as session:
        result = session.run(
            """
            MATCH (c:City)
            RETURN c.name AS name, c.location.y AS lat, c.location.x AS lon
            """
        )

        best_name: str | None = None
        best_dist: float | None = None
        for record in result:
            city_lat = record["lat"]
            city_lon = record["lon"]
            dist = haversine_distance(lat, lon, city_lat, city_lon)
            if best_dist is None or dist < best_dist:
                best_dist = dist
                best_name = record["name"]

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

    Parameters
    ----------
    flock_id : str
        The flock identifier (used only for counting; caller pre-computes count).
    is_new_flock : bool
        Whether this report caused a new flock to be created.
    report_count : int
        Total number of reports now stored for this flock (including this one).
    current_city : str | None
        Nearest city to the *current* report coordinates.
    last_report_city : str | None
        Nearest city to the *previous* report coordinates (``None`` if this is
        the very first report).

    Returns
    -------
    bool
    """
    # Rule 1: new flock
    if is_new_flock:
        return True

    # Rule 2: cumulative thresholds
    thresholds = _get_notification_thresholds()
    if _hits_threshold(report_count, thresholds):
        return True

    # Rule 3: town changed (both must be non-None to compare)
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

    # After level4, every multiple of level4 triggers
    if report_count >= level4 and report_count % level4 == 0:
        return True

    return False
