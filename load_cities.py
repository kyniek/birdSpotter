"""Load cities from a CSV file into Neo4j.

Usage:
    python load_cities.py cities.csv
    python load_cities.py --clean
"""
import csv
import sys

from app.neo4j_client import get_db


def clean_db():
    """Fully clean the Neo4j database: drop all indexes, constraints, and delete all nodes."""
    with get_db() as session:
        # Drop all constraints first (they may have backing indexes with the same name)
        constraints = session.run("SHOW CONSTRAINTS YIELD name RETURN name")
        for record in constraints:
            session.run("DROP CONSTRAINT $n", n=record["name"])

        # Drop all remaining indexes
        indexes = session.run("SHOW INDEXES YIELD name RETURN name")
        for record in indexes:
            session.run("DROP INDEX $n", n=record["name"])

        # Delete all nodes and relationships
        session.run("MATCH (n) DETACH DELETE n")

    print("Database cleaned: all nodes, relationships, indexes, and constraints removed.")


def load_cities(csv_path: str):
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
        for city in cities:
            session.run(
                """
                MERGE (c:City {name: $name})
                SET c.location = point({latitude: $lat, longitude: $lon})
                """,
                name=city["name"],
                lat=city["lat"],
                lon=city["lon"],
            )
    print(f"Loaded {len(cities)} cities from {csv_path}.")


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python load_cities.py <cities.csv> | --clean")
        sys.exit(1)

    if sys.argv[1] == "--clean":
        clean_db()
    else:
        load_cities(sys.argv[1])
