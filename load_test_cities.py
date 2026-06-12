"""Load cities from export.geojson into Neo4j for testing."""

import json
import os
import tempfile
from pathlib import Path

from load_cities import load_cities


_GEOJSON_PATH = Path(__file__).resolve().parent / "export.geojson"


def _load_all_cities() -> list[dict]:
    """Read all cities from export.geojson and return as a list of dicts."""
    with open(_GEOJSON_PATH, encoding="utf-8") as f:
        data = json.load(f)

    cities = []
    for feat in data.get("features", []):
        props = feat.get("properties", {})
        name_pl = props.get("name:pl") or props.get("name")
        place = props.get("place")
        if name_pl and place in ("city", "town"):
            coords = feat["geometry"]["coordinates"]
            lon, lat = coords[0], coords[1]
            cities.append({"name": name_pl, "lat": lat, "lon": lon})
    return cities


def compute_distance_between_cities(city_names: list[str]) -> list[dict]:
    """Compute distances between consecutive cities in the given list.

    For each city (except the last) the ``distance`` field holds the
    haversine distance in km to the next city.  The last city always has
    ``distance`` of ``0.0``.

    Parameters
    ----------
    city_names : list[str]
        Ordered list of city names (as they appear in export.geojson).

    Returns
    -------
    list[dict]
        One dict per city with keys ``name``, ``distance``, ``longitude``,
        ``latitude``.
    """
    from app.utils import haversine_distance

    all_cities = _load_all_cities()
    lookup = {c["name"]: c for c in all_cities}

    results: list[dict] = []
    for i, name in enumerate(city_names):
        city = lookup.get(name)
        if city is None:
            raise ValueError(f"City not found: {name}")

        if i < len(city_names) - 1:
            next_city = lookup.get(city_names[i + 1])
            if next_city is None:
                raise ValueError(f"City not found: {city_names[i + 1]}")
            dist = haversine_distance(
                city["lat"], city["lon"],
                next_city["lat"], next_city["lon"],
            )
        else:
            dist = 0.0

        results.append({
            "name": name,
            "distance": round(dist, 2),
            "longitude": city["lon"],
            "latitude": city["lat"],
        })

    return results


def load_cities_from_geojson(geojson_path: str) -> str:
    """Read cities from a GeoJSON FeatureCollection and return CSV text."""
    with open(geojson_path, encoding="utf-8") as f:
        data = json.load(f)

    lines = ["name,lat,lon"]
    for feat in data.get("features", []):
        props = feat.get("properties", {})
        name_pl = props.get("name:pl") or props.get("name")
        place = props.get("place")
        if name_pl and place in ("city", "town"):
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
