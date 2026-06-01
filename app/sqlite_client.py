"""SQLite database client — connection management and session context."""

import os
import sqlite3
import tempfile
from contextlib import contextmanager

from .config import settings


def _enable_spatialite(conn):
    """Enable SpatiaLite extension for spatial queries."""
    try:
        conn.enable_load_extension(True)
        conn.load_extension("mod_spatialite")
        conn.execute("SELECT InitSpatialMetadata()")
        conn.enable_load_extension(False)
    except Exception:
        # SpatiaLite not available — fall back to plain SQLite
        pass


@contextmanager
def get_db():
    """Yield a SQLite connection with autocommit behavior.

    During tests, uses the shared test database so that test fixtures and
    service functions operate on the same data.
    """
    # If a test temp file exists, use it (shared across all connections)
    if hasattr(get_test_db, "_tmp_path"):
        conn = sqlite3.connect(get_test_db._tmp_path)
    else:
        conn = sqlite3.connect(settings.db_path)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    _enable_spatialite(conn)
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


@contextmanager
def get_test_db():
    """Yield a test database connection.

    Uses a shared temporary file so that multiple connections in the same
    test session see the same data (unlike :memory: which creates a private
    database per connection).
    """
    # Use a module-level temp file path so all connections in this session
    # share the same database.
    if not hasattr(get_test_db, "_tmp_path"):
        fd, get_test_db._tmp_path = tempfile.mkstemp(suffix=".db", prefix="birdspotter_test_")
        os.close(fd)
    conn = sqlite3.connect(get_test_db._tmp_path)
    conn.execute("PRAGMA foreign_keys=ON")
    _enable_spatialite(conn)
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


# Lazy accessor for tests that need to patch
_test_conn = None


def _get_test_conn():
    """Return a persistent test connection (for fixtures that need it)."""
    global _test_conn
    if _test_conn is None:
        _test_conn = sqlite3.connect(settings.test_db_path)
    return _test_conn
