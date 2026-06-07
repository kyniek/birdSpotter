from app.neo4j_client import get_db


def init_schema():
    with get_db() as session:
        session.run(
            "CREATE CONSTRAINT flock_id IF NOT EXISTS "
            "FOR (f:Flock) REQUIRE f.id IS UNIQUE"
        )
        session.run(
            "CREATE CONSTRAINT report_id IF NOT EXISTS "
            "FOR (r:Report) REQUIRE r.id IS UNIQUE"
        )
        session.run(
            "CREATE CONSTRAINT coordinator_email IF NOT EXISTS "
            "FOR (c:Coordinator) REQUIRE c.email IS UNIQUE"
        )
        session.run(
            "CREATE CONSTRAINT city_name IF NOT EXISTS "
            "FOR (c:City) REQUIRE c.name IS UNIQUE"
        )
        session.run(
            "CREATE INDEX report_location IF NOT EXISTS "
            "FOR (r:Report) ON (r.location)"
        )
        session.run(
            "CREATE INDEX city_location IF NOT EXISTS "
            "FOR (c:City) ON (c.location)"
        )
    print("Schema created successfully.")


if __name__ == "__main__":
    init_schema()
