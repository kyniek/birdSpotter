"""Initialize Neo4j schema (constraints and indexes).

Usage:
    python init_db.py
"""

from app.lifecycle import _ensure_schema


def init_schema():
    """Legacy wrapper — delegates to lifecycle._ensure_schema()."""
    _ensure_schema()


if __name__ == "__main__":
    init_schema()
    print("Schema created successfully.")
