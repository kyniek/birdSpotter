"""Tests for compute_distance_between_cities in load_test_cities."""

import pytest

from load_test_cities import compute_distance_between_cities


class TestComputeDistanceBetweenCities:
    """Tests for the compute_distance_between_cities function."""

    def test_two_cities(self):
        """Two cities — first has distance, last has 0.0."""
        result = compute_distance_between_cities(["Przemyśl", "Pruchnik"])
        assert len(result) == 2

        przemyśl = result[0]
        assert przemyśl["name"] == "Przemyśl"
        assert isinstance(przemyśl["distance"], float)
        assert przemyśl["distance"] > 0
        assert "longitude" in przemyśl
        assert "latitude" in przemyśl

        pruchnik = result[1]
        assert pruchnik["name"] == "Pruchnik"
        assert pruchnik["distance"] == 0.0

    def test_three_cities(self):
        """Three cities — first two have distances, last has 0.0."""
        result = compute_distance_between_cities(
            ["Przemyśl", "Pruchnik", "Rzeszów"]
        )
        assert len(result) == 3
        assert result[0]["distance"] > 0
        assert result[1]["distance"] > 0
        assert result[2]["distance"] == 0.0

    def test_single_city(self):
        """Single city — distance is 0.0."""
        result = compute_distance_between_cities(["Przemyśl"])
        assert len(result) == 1
        assert result[0]["distance"] == 0.0

    def test_distance_is_rounded_to_two_decimals(self):
        """Distance values are rounded to 2 decimal places."""
        result = compute_distance_between_cities(["Przemyśl", "Pruchnik"])
        dist = result[0]["distance"]
        assert dist == round(dist, 2)

    def test_latitude_longitude_are_floats(self):
        """Latitude and longitude are floats, not strings."""
        result = compute_distance_between_cities(["Przemyśl", "Pruchnik"])
        for entry in result:
            assert isinstance(entry["latitude"], float)
            assert isinstance(entry["longitude"], float)

    def test_unknown_city_raises_value_error(self):
        """A city name not in export.geojson raises ValueError."""
        with pytest.raises(ValueError, match="City not found: NonexistentCity"):
            compute_distance_between_cities(["Przemyśl", "NonexistentCity"])

    def test_first_city_not_found_raises_value_error(self):
        """If the first city is unknown, ValueError is raised immediately."""
        with pytest.raises(ValueError, match="City not found: UnknownPlace"):
            compute_distance_between_cities(["UnknownPlace", "Przemyśl"])

    def test_result_keys_are_lowercase(self):
        """All result dict keys are lowercase."""
        result = compute_distance_between_cities(["Przemyśl", "Pruchnik"])
        for entry in result:
            assert set(entry.keys()) == {"name", "distance", "longitude", "latitude"}

    def test_distance_symmetry(self):
        """Distance A→B should equal distance B→A (haversine is symmetric)."""
        result_ab = compute_distance_between_cities(["Przemyśl", "Pruchnik"])
        result_ba = compute_distance_between_cities(["Pruchnik", "Przemyśl"])
        assert result_ab[0]["distance"] == result_ba[0]["distance"]
