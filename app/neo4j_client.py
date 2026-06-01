from neo4j import GraphDatabase, Driver
from redis import Redis

from .config import settings

# ── Neo4j ──────────────────────────────────────────────────────────────────────

driver = GraphDatabase.driver(
    settings.neo4j_uri,
    auth=(settings.neo4j_user, settings.neo4j_password),
)

# Test driver is created lazily to allow the test container to start first.
_test_driver: Driver | None = None


def _get_test_driver() -> Driver:
    """Lazily create and return the test Neo4j driver."""
    global _test_driver
    if _test_driver is None:
        _test_driver = GraphDatabase.driver(
            settings.neo4j_test_uri,
            auth=(settings.neo4j_test_user, settings.neo4j_test_password),
        )
    return _test_driver


# Public accessor — tests can call this after the container is up.
test_driver = _get_test_driver


def get_db():
    """Return a Neo4j session bound to the default database."""
    return driver.session(database="neo4j")


def get_test_db():
    """Return a Neo4j session bound to the test database."""
    return _get_test_driver().session(database="neo4j")


def close_driver():
    driver.close()
    if _test_driver is not None:
        _test_driver.close()


def close_test_driver():
    """Close only the test driver (useful in test teardown)."""
    if _test_driver is not None:
        _test_driver.close()


# ── Redis ──────────────────────────────────────────────────────────────────────

redis_client = Redis(
    host=settings.redis_host,
    port=settings.redis_port,
    decode_responses=True,
)
