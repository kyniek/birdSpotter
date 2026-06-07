"""Tests for load_cities.py."""

import os
import tempfile

import pytest

from load_cities import clean_db, load_cities
from load_test_cities import load_cities_from_geojson
from app.neo4j_client import get_db


@pytest.fixture(autouse=True, scope="session")
def neo4j_available():
    """Skip if Neo4j is down."""
    from app.neo4j_client import driver
    try:
        driver.verify_connectivity()
    except Exception as e:
        pytest.skip(f"Neo4j not reachable: {e}")
    yield


@pytest.fixture(autouse=True)
def ensure_clean_db():
    """Ensure DB is clean before and after each test."""
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
    with get_db() as session:
        result = session.run("MATCH (c:City) RETURN c.name AS name ORDER BY name")
        return [r["name"] for r in result]


def _index_count():
    """Return number of indexes in the database."""
    with get_db() as session:
        result = session.run("SHOW INDEXES YIELD name RETURN name")
        return sum(1 for _ in result)


def _constraint_count():
    """Return number of constraints in the database."""
    with get_db() as session:
        result = session.run("SHOW CONSTRAINTS YIELD name RETURN name")
        return sum(1 for _ in result)


def _node_count():
    """Return total number of nodes in the database."""
    with get_db() as session:
        result = session.run("MATCH (n) RETURN count(n) AS cnt")
        return list(result)[0]["cnt"]


class TestLoadCities:
    """Tests for load_cities()."""

    def test_load_cities_creates_nodes(self):
        """load_cities should create a City node for each row in the CSV."""
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
        """load_cities should store correct latitude and longitude."""
        csv_content = "name,lat,lon\nTestCity,50.00,21.00\n"
        fd, path = tempfile.mkstemp(suffix=".csv", text=True)
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                f.write(csv_content)
            load_cities(path)
        finally:
            os.unlink(path)

        with get_db() as session:
            result = session.run(
                "MATCH (c:City {name: $name}) RETURN c.latitude AS lat, c.longitude AS lon",
                name="TestCity",
            )
            row = list(result)[0]
            assert row["lat"] == 50.0
            assert row["lon"] == 21.0

    def test_load_cities_merges_on_name(self):
        """Calling load_cities twice with the same data should not duplicate nodes."""
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
        """clean_db should remove all nodes from the database."""
        # Create some test nodes
        with get_db() as session:
            session.run("CREATE (n:Temp {id: 1})")
            session.run("CREATE (n:Temp {id: 2})")
            session.run("MATCH (a:Temp {id: 1}), (b:Temp {id: 2}) CREATE (a)-[:REL]->(b)")

        assert _node_count() == 2

        clean_db()

        assert _node_count() == 0

    def test_clean_db_removes_indexes(self):
        """clean_db should drop all indexes."""
        # Create an index
        with get_db() as session:
            session.run("CREATE INDEX test_idx FOR (n:Temp) ON (n.id)")

        assert _index_count() > 0

        clean_db()

        assert _index_count() == 0

    def test_clean_db_removes_constraints(self):
        """clean_db should drop all constraints."""
        # Create a constraint (on a property with no existing index)
        with get_db() as session:
            session.run("CREATE CONSTRAINT test_constraint FOR (n:Temp) REQUIRE n.email IS UNIQUE")

        assert _constraint_count() > 0

        clean_db()

        assert _constraint_count() == 0

    def test_clean_db_is_idempotent(self):
        """Calling clean_db multiple times should not raise errors."""
        clean_db()
        clean_db()
        clean_db()
        assert _node_count() == 0


class TestIntegration:
    """Integration tests: load from geojson, verify, clean, verify cleanup."""

    def test_load_from_geojson_and_verify(self):
        """Loading cities from export.geojson should create the correct City nodes."""
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
        """After loading from geojson and cleaning, DB should be completely empty."""
        # Load cities
        geojson_path = os.path.join(os.path.dirname(__file__), "export.geojson")
        csv_text = load_cities_from_geojson(geojson_path)
        fd, path = tempfile.mkstemp(suffix=".csv", text=True)
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                f.write(csv_text)
            load_cities(path)
        finally:
            os.unlink(path)

        # Verify cities were loaded
        assert _node_count() > 0

        # Clean
        clean_db()

        # Verify everything is gone
        assert _node_count() == 0
        assert _index_count() == 0
        assert _constraint_count() == 0

        # Verify SHOW INDEXES, SHOW CONSTRAINTS return empty
        with get_db() as session:
            indexes = session.run("SHOW INDEXES YIELD name RETURN name")
            assert sum(1 for _ in indexes) == 0

            constraints = session.run("SHOW CONSTRAINTS YIELD name RETURN name")
            assert sum(1 for _ in constraints) == 0

    def test_load_clean_load_again(self):
        """Load cities, clean, load again — should work without errors."""
        geojson_path = os.path.join(os.path.dirname(__file__), "export.geojson")
        csv_text = load_cities_from_geojson(geojson_path)
        fd, path = tempfile.mkstemp(suffix=".csv", text=True)
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                f.write(csv_text)

            # First load
            load_cities(path)
            assert _node_count() > 0

            # Clean
            clean_db()
            assert _node_count() == 0

            # Second load — should succeed without constraint/index errors
            load_cities(path)
            assert _node_count() > 0
        finally:
            os.unlink(path)
