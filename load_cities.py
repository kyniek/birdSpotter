"""Load cities from a CSV file or export.geojson into Neo4j.

Usage:
    python load_cities.py cities.csv        # Load from CSV
    python load_cities.py --geojson         # Load from export.geojson
    python load_cities.py --clean           # Wipe all data
"""
import csv
import sys

from app.lifecycle import _load_cities_if_missing


def clean_db():
    """Fully clean the Neo4j database: drop all indexes, constraints, and delete all nodes."""
    from app.neo4j_client import get_db

    with get_db() as session:
        constraints = session.run("SHOW CONSTRAINTS YIELD name RETURN name")
        for record in constraints:
            session.run("DROP CONSTRAINT $n", n=record["name"])

        indexes = session.run("SHOW INDEXES YIELD name RETURN name")
        for record in indexes:
            session.run("DROP INDEX $n", n=record["name"])

        session.run("MATCH (n) DETACH DELETE n")

    print("Database cleaned: all nodes, relationships, indexes, and constraints removed.")


def load_cities(csv_path: str):
    from app.neo4j_client import get_db

    with open(csv_path, newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        cities = []
        for row in reader:
            cities.append(
                {
                    "name": row["name"].strip(),
                    "lat": float(row["lat"]),
                    "lon": float(row["lon"]),
                }
            )

    with get_db() as session:
        for c in cities:
            session.run(
                """
                MERGE (c:City {name: $name})
                SET c.location = point({latitude: $lat, longitude: $lon})
                """,
                name=c["name"],
                lat=c["lat"],
                lon=c["lon"],
            )
    print(f"Loaded {len(cities)} cities from {csv_path}.")


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python load_cities.py <cities.csv> | --geojson | --clean")
        sys.exit(1)

    if sys.argv[1] == "--clean":
        clean_db()
    elif sys.argv[1] == "--geojson":
        _load_cities_if_missing()
    else:
        load_cities(sys.argv[1])
