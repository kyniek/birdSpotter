import os
from pathlib import Path

import yaml
from pydantic_settings import BaseSettings


def _load_pass_yaml():
    """Load pass.yaml from the project root and return as a flat dict."""
    pass_path = Path(__file__).resolve().parent.parent / "pass.yaml"
    if pass_path.exists():
        with open(pass_path) as f:
            data = yaml.safe_load(f)
        # Flatten: {neo4j: {password: x}} -> {"neo4j_password": x}
        flat = {}
        for section, fields in (data or {}).items():
            if isinstance(fields, dict):
                for key, value in fields.items():
                    flat[f"{section}_{key}"] = value
        return flat
    return {}


_pass_data = _load_pass_yaml()


class Settings(BaseSettings):
    neo4j_uri: str = "bolt://localhost:7687"
    neo4j_user: str = "neo4j"
    neo4j_password: str = _pass_data.get("neo4j_password", "")

    neo4j_test_uri: str = "bolt://localhost:7688"
    neo4j_test_user: str = "neo4j"
    neo4j_test_password: str = _pass_data.get("neo4j_test_password", "")

    smtp_host: str = "smtp.gmail.com"
    smtp_port: int = 587
    smtp_user: str = ""
    smtp_password: str = _pass_data.get("smtp_password", "")

    redis_host: str = "localhost"
    redis_port: int = 6379

    v_max_kmh: float = 100.0
    silence_window_hours: int = 10
    bearing_tolerance_deg: float = 30.0

    model_config = {"env_file": ".env", "env_file_encoding": "utf-8"}

    @classmethod
    def settings_customise_sources(cls, settings_cls, init_settings, env_settings, dotenv_settings, file_secret_settings):
        # .env takes priority over shell env vars so the file always wins
        return (init_settings, dotenv_settings, env_settings, file_secret_settings)


settings = Settings()
