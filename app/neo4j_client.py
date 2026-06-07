from neo4j import GraphDatabase
from redis import Redis

from .config import settings

# ── Neo4j ──────────────────────────────────────────────────────────────────────

driver = GraphDatabase.driver(
    settings.neo4j_uri,
    auth=(settings.neo4j_user, settings.neo4j_password),
)


def get_db():
    """Return a Neo4j session bound to the default database."""
    return driver.session(database="neo4j")


def close_driver():
    driver.close()


# ── Redis ──────────────────────────────────────────────────────────────────────

redis_client = Redis(
    host=settings.redis_host,
    port=settings.redis_port,
    decode_responses=True,
)
