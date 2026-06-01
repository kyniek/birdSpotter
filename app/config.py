from pathlib import Path

import yaml
from pydantic_settings import BaseSettings


def _load_pass_creds() -> dict:
    """Load SMTP credentials from pass.yaml."""
    pass_file = Path(__file__).parent.parent / "pass.yaml"
    if not pass_file.exists():
        return {}
    with open(pass_file) as f:
        return yaml.safe_load(f) or {}


def get_smtp_user() -> str:
    creds = _load_pass_creds()
    return creds.get("imap", {}).get("user", "")


def get_smtp_password() -> str:
    creds = _load_pass_creds()
    return creds.get("smtp", {}).get("password", "")


class Settings(BaseSettings):
    # Database
    db_path: str = "birdspotter.db"
    test_db_path: str = ":memory:"

    # SMTP host/port (these are not secrets)
    smtp_host: str = "smtp.gmail.com"
    smtp_port: int = 587

    # Flock algorithm parameters
    v_max_kmh: float = 100.0
    silence_window_hours: int = 10
    bearing_tolerance_deg: float = 30.0

    # Notification thresholds (cumulative report counts)
    notification_threshold_level1: int = 1
    notification_threshold_level2: int = 5
    notification_threshold_level3: int = 25
    notification_threshold_level4: int = 100

    model_config = {"env_file": ".env", "env_file_encoding": "utf-8"}

    @classmethod
    def settings_customise_sources(
        cls, settings_cls, init_settings, env_settings, dotenv_settings, file_secret_settings
    ):
        return (init_settings, dotenv_settings, env_settings, file_secret_settings)


settings = Settings()
