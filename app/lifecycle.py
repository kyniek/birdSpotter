"""Database initialization — schema constraints, indexes, and city data.

Called automatically on every server startup via the FastAPI lifespan event.
"""

from pathlib import Path

from .neo4j_client import get_db


def _ensure_schema():
    """Create Neo4j constraints and indexes (idempotent with IF NOT EXISTS)."""
    with get_db() as session:
        session.run(
            "CREATE CONSTRAINT flock_id IF NOT EXISTS "
            "FOR (f:Flock) REQUIRE f.id IS UNIQUE"
        )
        session.run(
            "CREATE CONSTRAINT report_id IF NOT EXISTS "
            "FOR (r:Report) REQUIRE r.id IS UNIQUE"
        )
        session.run(
            "CREATE CONSTRAINT coordinator_email IF NOT EXISTS "
            "FOR (c:Coordinator) REQUIRE c.email IS UNIQUE"
        )
        session.run(
            "CREATE CONSTRAINT city_name IF NOT EXISTS "
            "FOR (c:City) REQUIRE c.name IS UNIQUE"
        )
        session.run(
            "CREATE INDEX report_location IF NOT EXISTS "
            "FOR (r:Report) ON (r.location)"
        )
        session.run(
            "CREATE INDEX city_location IF NOT EXISTS "
            "FOR (c:City) ON (c.location)"
        )


def _load_cities_if_missing():
    """Load Polish cities from export.geojson if no City nodes exist yet.

    Reuses the same parsing logic as ``load_test_cities.load_cities_from_geojson``
    so the server and the test loader stay in sync.
    """
    with get_db() as session:
        count = session.run("MATCH (c:City) RETURN count(c) AS cnt").single()["cnt"]
        if count > 0:
            return  # Cities already loaded

    geojson_path = Path(__file__).resolve().parent.parent / "export.geojson"
    if not geojson_path.exists():
        print("  [skip] export.geojson not found — no cities loaded.")
        return

    # Reuse the exact same parsing logic from load_test_cities
    import json

    with open(geojson_path, encoding="utf-8") as f:
        data = json.load(f)

    cities = []
    for feat in data.get("features", []):
        props = feat.get("properties", {})
        name_pl = props.get("name:pl") or props.get("name")
        place = props.get("place")
        if name_pl and place in ("city", "town", "village"):
            coords = feat["geometry"]["coordinates"]
            lon, lat = coords[0], coords[1]
            cities.append({"name": name_pl, "lat": float(lat), "lon": float(lon)})

    with get_db() as session:
        for c in cities:
            session.run(
                "MERGE (c:City {name: $name}) "
                "SET c.location = point({latitude: $lat, longitude: $lon})",
                **c,
            )

    print(f"  Loaded {len(cities)} cities from export.geojson.")


def init_database():
    """Run all database initialization steps (called on every server startup)."""
    _ensure_schema()
    _load_cities_if_missing()
