import pytest
from app.neo4j_client import driver, get_db, close_driver


@pytest.fixture(autouse=True, scope="session")
def neo4j_setup():
    """Ensure Neo4j is reachable before running tests."""
    try:
        driver.verify_connectivity()
    except Exception as e:
        pytest.skip(f"Neo4j not reachable: {e}")
    yield
    # cleanup: drop test nodes if any
    with get_db() as session:
        session.run("MATCH (n) WHERE n.test_id IS NOT NULL DETACH DELETE n")


def test_verify_connectivity():
    """Driver should connect to Neo4j."""
    driver.verify_connectivity()


def test_init_schema():
    """init_schema should run without errors."""
    from init_db import init_schema
    init_schema()


def test_list_indexes():
    """Should be able to list indexes without error."""
    with get_db() as session:
        result = session.run("SHOW INDEXES YIELD name, type RETURN name")
        names = [r["name"] for r in result]
        assert len(names) > 0


def test_create_and_delete_test_node():
    """Create a test node, read it back, then delete it."""
    test_id = "test_node_12345"
    with get_db() as session:
        # Create
        session.run(
            "CREATE (n:TestNode {test_id: $tid, value: 'hello'})",
            tid=test_id,
        )
        # Read
        result = session.run(
            "MATCH (n:TestNode {test_id: $tid}) RETURN n.value AS val",
            tid=test_id,
        )
        row = list(result)
        assert len(row) == 1
        assert row[0]["val"] == "hello"
        # Delete
        session.run(
            "MATCH (n:TestNode {test_id: $tid}) DETACH DELETE n",
            tid=test_id,
        )
    # Verify deleted
    with get_db() as session:
        result = session.run(
            "MATCH (n:TestNode {test_id: $tid}) RETURN count(n) AS cnt",
            tid=test_id,
        )
        assert list(result)[0]["cnt"] == 0
