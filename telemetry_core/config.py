"""
CarDigno - Centralized System Configuration
Safely loads environment configurations with secure defaults.
Prevents sensitive information, database paths, and secrets from being hardcoded.
"""

import os
import logging
from pathlib import Path
from typing import List, Optional

logger = logging.getLogger("CarDignoConfig")

# Base directory of the repository
BASE_DIR = Path(__file__).resolve().parent.parent


def _load_dotenv(env_path: Optional[Path] = None) -> None:
    """
    Lightweight .env loader without requiring third-party dependencies.
    Reads key=value pairs into os.environ if not already set.
    """
    path = env_path or (BASE_DIR / ".env")
    if not path.is_file():
        return

    try:
        with open(path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                key, val = line.split("=", 1)
                key = key.strip()
                val = val.strip().strip("\"'")
                if key not in os.environ:
                    os.environ[key] = val
    except Exception as e:
        logger.warning(f"Could not load .env file from {path}: {e}")


# Automatically attempt to load .env on module import
_load_dotenv()


class Settings:
    """Application and Telemetry Settings."""

    # Environment
    ENV: str = os.getenv("CARDIGNO_ENV", "development").lower()

    # Telemetry Simulator Settings
    SIM_HOST: str = os.getenv("CARDIGNO_SIM_HOST", "127.0.0.1")
    SIM_PORT: int = int(os.getenv("CARDIGNO_SIM_PORT", "8000"))
    SIM_RATE_HZ: float = float(os.getenv("CARDIGNO_SIM_RATE_HZ", "10.0"))

    # Telemetry Ingestion & Storage Settings
    _default_db = str(BASE_DIR / "database" / "telemetry.db")
    DB_PATH: str = os.getenv("CARDIGNO_DB_PATH", _default_db)
    BATCH_SIZE: int = int(os.getenv("CARDIGNO_BATCH_SIZE", "10"))

    # Application API & WebSocket Service (Phases 4-5)
    API_HOST: str = os.getenv("CARDIGNO_API_HOST", "127.0.0.1")
    API_PORT: int = int(os.getenv("CARDIGNO_API_PORT", "8080"))
    CORS_ORIGINS: List[str] = [
        origin.strip()
        for origin in os.getenv(
            "CARDIGNO_CORS_ORIGINS",
            "http://localhost:3000,http://127.0.0.1:3000,http://localhost:8080"
        ).split(",")
        if origin.strip()
    ]

    # Security & Authentication
    SECRET_KEY: str = os.getenv("CARDIGNO_SECRET_KEY", "insecure-dev-secret-key-change-in-prod")

    # Logging
    LOG_LEVEL: str = os.getenv("CARDIGNO_LOG_LEVEL", "INFO").upper()

    @classmethod
    def validate_security(cls) -> None:
        """Logs warnings if insecure settings are detected."""
        if cls.SIM_HOST == "0.0.0.0" or cls.API_HOST == "0.0.0.0":
            logger.warning(
                "SECURITY WARNING: Host bound to 0.0.0.0. Services are exposed to public network interfaces."
            )
        if cls.ENV == "production" and "insecure" in cls.SECRET_KEY:
            logger.warning(
                "SECURITY CRITICAL: Default SECRET_KEY in use in production environment! Set CARDIGNO_SECRET_KEY in .env."
            )


# Global settings singleton
settings = Settings()
