"""Load cities from a CSV file or export.geojson into SQLite.

Usage:
    python load_cities.py cities.csv        # Load from CSV
    python load_cities.py --geojson         # Load from export.geojson
    python load_cities.py --clean           # Wipe all data
"""
import csv
import sys

from app.lifecycle import _load_cities_if_missing


def clean_db():
    """Fully clean the SQLite database: delete all rows."""
    from app.sqlite_client import get_db

    with get_db() as conn:
        conn.execute("DELETE FROM flock_coordinators")
        conn.execute("DELETE FROM reports")
        conn.execute("DELETE FROM flocks")
        conn.execute("DELETE FROM coordinators")
        conn.execute("DELETE FROM cities")
        conn.commit()

    print("Database cleaned: all rows removed.")


def load_cities(csv_path: str):
    from app.sqlite_client import get_db

    with open(csv_path, newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        cities = []
        for row in reader:
            cities.append(
                (
                    row["name"].strip(),
                    float(row["lat"]),
                    float(row["lon"]),
                )
            )

    with get_db() as conn:
        conn.executemany(
            "INSERT OR REPLACE INTO cities (name, latitude, longitude) VALUES (?, ?, ?)",
            cities,
        )
        conn.commit()
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
