"""Initialize Neo4j schema (constraints and indexes).

Usage:
    python init_db.py
"""

from app.lifecycle import _ensure_schema


def init_schema():
    """Legacy wrapper — delegates to lifecycle._ensure_schema(conn)."""
    from app.config import settings
    from app.sqlite_client import get_db

    with get_db() as conn:
        _ensure_schema(conn)


if __name__ == "__main__":
    init_schema()
    print("Schema created successfully.")
