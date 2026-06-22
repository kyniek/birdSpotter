"""Tests for app/sqlite_client.py."""

import pytest
import sqlite3

from app.sqlite_client import get_db, get_test_db, _get_test_conn
from app.lifecycle import _ensure_schema


def test_get_db_connects():
    """get_db should connect and return a usable connection."""
    with get_db() as conn:
        result = conn.execute("SELECT 1").fetchone()
        assert result[0] == 1


def test_get_test_db_connects():
    """get_test_db should connect to in-memory DB."""
    with get_test_db() as conn:
        result = conn.execute("SELECT 1").fetchone()
        assert result[0] == 1


def test_ensure_schema():
    """_ensure_schema should create all tables without error."""
    with get_test_db() as conn:
        _ensure_schema(conn)
        # Verify tables exist
        cursor = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name"
        )
        tables = [row[0] for row in cursor]
        assert "flocks" in tables
        assert "reports" in tables
        assert "coordinators" in tables
        assert "flock_coordinators" in tables
        assert "cities" in tables


def test_create_and_read():
    """Create a flock and report, read it back."""
    with get_test_db() as conn:
        _ensure_schema(conn)
        conn.execute("INSERT INTO flocks (id) VALUES (?)", ("test-flock-1",))
        conn.execute(
            "INSERT INTO reports (id, flock_id, latitude, longitude, timestamp) VALUES (?, ?, ?, ?, ?)",
            ("test-report-1", "test-flock-1", 52.0, 21.0, "2026-01-01T00:00:00"),
        )
        conn.commit()

        cursor = conn.execute(
            "SELECT id, flock_id, latitude, longitude FROM reports"
        )
        row = cursor.fetchone()
        assert row[0] == "test-report-1"
        assert row[1] == "test-flock-1"
        assert row[2] == 52.0
        assert row[3] == 21.0


def test_foreign_keys():
    """Foreign key constraints should be enforced."""
    with get_test_db() as conn:
        _ensure_schema(conn)
        with pytest.raises(sqlite3.IntegrityError):
            conn.execute(
                "INSERT INTO reports (id, flock_id, latitude, longitude, timestamp) VALUES (?, ?, ?, ?, ?)",
                ("bad-report", "nonexistent-flock", 52.0, 21.0, "2026-01-01T00:00:00"),
            )
            conn.commit()
