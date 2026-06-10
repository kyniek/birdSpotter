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

def predict_city(lat: float, lon: float, bearing: float) -> tuple[str, float] | None:
    """Predict which city the flock is heading toward.

    Filters cities within ``BEARING_TOLERANCE_DEG`` of *bearing*, then returns
    the closest one as ``(city_name, distance_km)`` or ``None``.
    """
    tolerance = settings.bearing_tolerance_deg

    with get_db() as session:
        result = session.run(
            """
            MATCH (c:City)
            RETURN c.name AS name, c.location.y AS lat, c.location.x AS lon
            """
        )

        best: dict | None = None
        for record in result:
            city_lat = record["lat"]
            city_lon = record["lon"]
            city_bearing = calculate_bearing(lat, lon, city_lat, city_lon)
            diff = angle_difference(bearing, city_bearing)
            if diff <= tolerance:
                dist = haversine_distance(lat, lon, city_lat, city_lon)
                if best is None or dist < best["dist"]:
                    best = {"name": record["name"], "dist": dist}

    if best is not None:
        return best["name"], best["dist"]
    return None


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
