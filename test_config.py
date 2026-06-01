import os

from app.config import Settings


def test_default_values():
    """Settings should load defaults when no env vars are set."""
    # Clear any relevant env vars
    for key in list(os.environ):
        if key.startswith("NEO4J_") or key.startswith("V_MAX") or key.startswith("SMTP") or key.startswith("REDIS"):
            del os.environ[key]
    s = Settings(_env_file=None)
    assert s.v_max_kmh == 100.0
    assert s.silence_window_hours == 10
    assert s.bearing_tolerance_deg == 30.0
    assert s.neo4j_uri == "bolt://localhost:7687"
    assert s.smtp_port == 587


def test_env_override():
    """Environment variables should override defaults."""
    import importlib
    # Force re-import with fresh env
    os.environ["V_MAX_KMH"] = "120"
    os.environ["SILENCE_WINDOW_HOURS"] = "5"
    os.environ["BEARING_TOLERANCE_DEG"] = "45"
    try:
        s = Settings(_env_file=None)
        assert s.v_max_kmh == 120.0
        assert s.silence_window_hours == 5
        assert s.bearing_tolerance_deg == 45.0
    finally:
        del os.environ["V_MAX_KMH"]
        del os.environ["SILENCE_WINDOW_HOURS"]
        del os.environ["BEARING_TOLERANCE_DEG"]
