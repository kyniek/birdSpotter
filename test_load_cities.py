"""Tests for load_cities.py."""

import os
import tempfile

import pytest

from load_cities import clean_db, load_cities
from load_test_cities import load_cities_from_geojson
from app.sqlite_client import get_test_db


@pytest.fixture(autouse=True)
def ensure_clean_db():
    """Ensure DB is clean before and after each test."""
    from app.lifecycle import _ensure_schema
    with get_test_db() as conn:
        _ensure_schema(conn)
    clean_db()
    yield
    clean_db()


def _expected_cities():
    """Return the list of expected city names from export.geojson."""
    geojson_path = os.path.join(os.path.dirname(__file__), "export.geojson")
    csv_text = load_cities_from_geojson(geojson_path)
    lines = csv_text.strip().splitlines()[1:]  # skip header
    return sorted(line.split(",")[0] for line in lines)


def _city_names_in_db():
    """Return sorted list of city names currently in the database."""
    with get_test_db() as conn:
        cursor = conn.execute("SELECT name FROM cities ORDER BY name")
        return [row[0] for row in cursor]


def _row_count(table):
    """Return number of rows in a table."""
    with get_test_db() as conn:
        cursor = conn.execute(f"SELECT COUNT(*) FROM {table}")
        return cursor.fetchone()[0]


def _node_count():
    """Return total number of rows across all tables."""
    with get_test_db() as conn:
        total = 0
        for table in ["flocks", "reports", "coordinators", "flock_coordinators", "cities"]:
            cursor = conn.execute(f"SELECT COUNT(*) FROM {table}")
            total += cursor.fetchone()[0]
        return total


class TestLoadCities:
    """Tests for load_cities()."""

    def test_load_cities_creates_nodes(self):
        csv_content = "name,lat,lon\nLublin,51.25,22.57\nZamość,50.72,23.25\n"
        fd, path = tempfile.mkstemp(suffix=".csv", text=True)
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                f.write(csv_content)
            load_cities(path)
        finally:
            os.unlink(path)

        names = _city_names_in_db()
        assert "Lublin" in names
        assert "Zamość" in names
        assert len(names) == 2

    def test_load_cities_sets_coordinates(self):
        csv_content = "name,lat,lon\nTestCity,50.00,21.00\n"
        fd, path = tempfile.mkstemp(suffix=".csv", text=True)
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                f.write(csv_content)
            load_cities(path)
        finally:
            os.unlink(path)

        with get_test_db() as conn:
            cursor = conn.execute(
                "SELECT latitude, longitude FROM cities WHERE name = ?",
                ("TestCity",),
            )
            row = cursor.fetchone()
            assert row[0] == pytest.approx(50.0, abs=1e-6)
            assert row[1] == pytest.approx(21.0, abs=1e-6)

    def test_load_cities_merges_on_name(self):
        csv_content = "name,lat,lon\nLublin,51.25,22.57\n"
        fd, path = tempfile.mkstemp(suffix=".csv", text=True)
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                f.write(csv_content)
            load_cities(path)
            load_cities(path)
        finally:
            os.unlink(path)

        names = _city_names_in_db()
        assert names.count("Lublin") == 1


class TestCleanDb:
    """Tests for clean_db()."""

    def test_clean_db_removes_all_nodes(self):
        with get_test_db() as conn:
            conn.execute("INSERT INTO flocks (id) VALUES ('temp1')")
            conn.execute("INSERT INTO flocks (id) VALUES ('temp2')")
            conn.commit()

        assert _node_count() == 2

        clean_db()

        assert _node_count() == 0

    def test_clean_db_is_idempotent(self):
        clean_db()
        clean_db()
        clean_db()
        assert _node_count() == 0


class TestIntegration:
    """Integration tests: load from geojson, verify, clean, verify cleanup."""

    def test_load_from_geojson_and_verify(self):
        expected = _expected_cities()

        geojson_path = os.path.join(os.path.dirname(__file__), "export.geojson")
        csv_text = load_cities_from_geojson(geojson_path)
        fd, path = tempfile.mkstemp(suffix=".csv", text=True)
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                f.write(csv_text)
            load_cities(path)
        finally:
            os.unlink(path)

        actual = _city_names_in_db()
        assert sorted(actual) == expected

    def test_load_from_geojson_clean_and_verify_no_leftovers(self):
        geojson_path = os.path.join(os.path.dirname(__file__), "export.geojson")
        csv_text = load_cities_from_geojson(geojson_path)
        fd, path = tempfile.mkstemp(suffix=".csv", text=True)
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                f.write(csv_text)
            load_cities(path)
        finally:
            os.unlink(path)

        assert _node_count() > 0

        clean_db()

        assert _node_count() == 0

    def test_load_clean_load_again(self):
        geojson_path = os.path.join(os.path.dirname(__file__), "export.geojson")
        csv_text = load_cities_from_geojson(geojson_path)
        fd, path = tempfile.mkstemp(suffix=".csv", text=True)
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                f.write(csv_text)

            load_cities(path)
            assert _node_count() > 0

            clean_db()
            assert _node_count() == 0

            load_cities(path)
            assert _node_count() > 0
        finally:
            os.unlink(path)
