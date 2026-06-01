import pytest
from app.utils import haversine_distance, calculate_bearing, angle_difference


def test_haversine_same_point():
    assert haversine_distance(52.23, 21.01, 52.23, 21.01) == pytest.approx(0, abs=1e-6)


def test_haversine_warsaw_krakow():
    # Warsaw to Kraków ≈ 250-280 km
    dist = haversine_distance(52.23, 21.01, 50.06, 19.94)
    assert 240 <= dist <= 290


def test_haversine_known_distance():
    # New York to London ≈ 5570 km
    dist = haversine_distance(40.71, -74.01, 51.51, -0.13)
    assert 5500 <= dist <= 5700


def test_bearing_equator_to_north_pole():
    # From equator (0, 0) to North Pole (90, 0) → bearing 0°
    b = calculate_bearing(0, 0, 90, 0)
    assert b == pytest.approx(0, abs=0.1)


def test_bearing_west():
    # From (0, 0) to (0, -90) → bearing 270°
    b = calculate_bearing(0, 0, 0, -90)
    assert b == pytest.approx(270, abs=0.1)


def test_angle_difference_small():
    assert angle_difference(10, 30) == 20


def test_angle_difference_wrap():
    # 350° and 10° → difference is 20°
    assert angle_difference(350, 10) == 20


def test_angle_difference_opposite():
    # 0° and 180° → difference is 180°
    assert angle_difference(0, 180) == 180


def test_angle_difference_large_wrap():
    # 10° and 350° → difference is 20°
    assert angle_difference(10, 350) == 20
