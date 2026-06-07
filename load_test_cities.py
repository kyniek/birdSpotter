"""Load cities from export.geojson into Neo4j for testing."""

import json
import os
import tempfile

from load_cities import load_cities


def load_cities_from_geojson(geojson_path: str) -> str:
    """Read cities from a GeoJSON FeatureCollection and return CSV text."""
    with open(geojson_path, encoding="utf-8") as f:
        data = json.load(f)

    lines = ["name,lat,lon"]
    for feat in data.get("features", []):
        props = feat.get("properties", {})
        name_pl = props.get("name:pl")
        place = props.get("place")
        if name_pl and place in ("city", "town", "village"):
            coords = feat["geometry"]["coordinates"]
            # GeoJSON uses [lon, lat] order
            lon, lat = coords[0], coords[1]
            lines.append(f"{name_pl},{lat},{lon}")

    return "\n".join(lines)


def main():
    geojson_path = os.path.join(os.path.dirname(__file__), "export.geojson")
    csv_text = load_cities_from_geojson(geojson_path)
    print(f"Loaded {len(csv_text.splitlines()) - 1} cities from {geojson_path}")

    # Write temporary CSV and load
    fd, path = tempfile.mkstemp(suffix=".csv", text=True)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(csv_text)
        load_cities(path)
    finally:
        os.unlink(path)


if __name__ == "__main__":
    main()
