"""Database initialization — schema creation and city data loading.

Called automatically on every server startup via the FastAPI lifespan event.
"""

from pathlib import Path

from .sqlite_client import get_db


def _ensure_schema(conn):
    """Create tables (idempotent with IF NOT EXISTS).

    Accepts a connection so that tests can pass their test DB connection.
    """
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS flocks (
            id TEXT PRIMARY KEY
        );

        CREATE TABLE IF NOT EXISTS reports (
            id TEXT PRIMARY KEY,
            flock_id TEXT NOT NULL REFERENCES flocks(id),
            latitude REAL NOT NULL,
            longitude REAL NOT NULL,
            timestamp TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS coordinators (
            email TEXT PRIMARY KEY
        );

        CREATE TABLE IF NOT EXISTS flock_coordinators (
            flock_id TEXT NOT NULL REFERENCES flocks(id),
            coordinator_email TEXT NOT NULL REFERENCES coordinators(email),
            PRIMARY KEY (flock_id, coordinator_email)
        );

        CREATE TABLE IF NOT EXISTS cities (
            name TEXT PRIMARY KEY,
            latitude REAL NOT NULL,
            longitude REAL NOT NULL
        );

        CREATE INDEX IF NOT EXISTS idx_reports_flock ON reports(flock_id);
        CREATE INDEX IF NOT EXISTS idx_reports_timestamp ON reports(timestamp);
    """)

    # SpatiaLite geometry column for spatial queries (optional)
    try:
        conn.execute("SELECT AddGeometryColumn('cities', 'geom', 4326, 'POINT', 'XY')")
        conn.execute("SELECT CreateSpatialIndex('cities', 'geom')")
    except Exception:
        # SpatiaLite not available — skip geometry column
        pass


def _load_cities_if_missing():
    """Load Polish cities from export.geojson if no City rows exist yet.

    Reuses the same parsing logic as ``load_test_cities.load_cities_from_geojson``
    so the server and the test loader stay in sync.
    """
    with get_db() as conn:
        cursor = conn.execute("SELECT COUNT(*) FROM cities")
        if cursor.fetchone()[0] > 0:
            return  # Cities already loaded

    geojson_path = Path(__file__).resolve().parent.parent / "export.geojson"
    if not geojson_path.exists():
        print("  [skip] export.geojson not found — no cities loaded.")
        return

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
            cities.append((name_pl, float(lat), float(lon)))

    with get_db() as conn:
        conn.executemany(
            "INSERT OR REPLACE INTO cities (name, latitude, longitude) VALUES (?, ?, ?)",
            cities,
        )

    print(f"  Loaded {len(cities)} cities from export.geojson.")


def init_database():
    """Run all database initialization steps (called on every server startup)."""
    with get_db() as conn:
        _ensure_schema(conn)
    _load_cities_if_missing()
