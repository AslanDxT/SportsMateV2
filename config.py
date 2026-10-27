"""
SportsMate settings.

All settings come from environment variables. For local development you can
put them in a `.env` file next to this file (see `.env.example`). Real
environment variables always win over values in `.env`.
"""

import os
import secrets
from datetime import timedelta
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent

APP_VERSION = "2.0.0"


def load_dotenv(path=None):
    """Read KEY=VALUE lines from a .env file into os.environ (no dependency needed)."""
    path = Path(path) if path else BASE_DIR / ".env"
    if not path.is_file():
        return

    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        if key:
            os.environ.setdefault(key, value)


def env_bool(name, default=False):
    value = os.environ.get(name)
    if value is None or value.strip() == "":
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def env_int(name, default):
    try:
        return int(os.environ.get(name, default))
    except (TypeError, ValueError):
        return default


def _secret_key(environment, instance_dir):
    """
    Return the key used to sign session cookies.

    Production must set SECRET_KEY. In development a random key is generated
    once and stored in instance/secret_key, so you stay logged in after a
    restart but the key is never part of the source code.
    """
    key = os.environ.get("SECRET_KEY", "").strip()
    if key:
        return key

    if environment == "production":
        raise RuntimeError(
            "SECRET_KEY is not set. Set a long random SECRET_KEY "
            "environment variable before running SportsMate in production."
        )

    key_file = instance_dir / "secret_key"
    if key_file.is_file():
        stored = key_file.read_text(encoding="utf-8").strip()
        if stored:
            return stored

    instance_dir.mkdir(parents=True, exist_ok=True)
    key = secrets.token_hex(32)
    key_file.write_text(key, encoding="utf-8")
    return key


def build_config():
    load_dotenv()

    environment = os.environ.get("SPORTSMATE_ENV", "development").strip().lower()
    instance_dir = Path(os.environ.get("SPORTSMATE_INSTANCE_DIR", BASE_DIR / "instance"))

    return {
        "ENVIRONMENT": environment,
        "SECRET_KEY": _secret_key(environment, instance_dir),
        "DATABASE_PATH": os.environ.get("DATABASE_PATH", str(BASE_DIR / "sportsmate.db")),
        "BACKUP_DIR": os.environ.get("BACKUP_DIR", str(BASE_DIR / "backups")),
        "INSTANCE_DIR": str(instance_dir),

        # Session cookie hardening
        "SESSION_COOKIE_HTTPONLY": True,
        "SESSION_COOKIE_SAMESITE": "Lax",
        "SESSION_COOKIE_SECURE": env_bool("SESSION_COOKIE_SECURE", environment == "production"),
        "PERMANENT_SESSION_LIFETIME": timedelta(days=env_int("SESSION_DAYS", 14)),

        # Forms are small; refuse huge request bodies.
        "MAX_CONTENT_LENGTH": 256 * 1024,

        # Security features (only tests should switch these off)
        "CSRF_ENABLED": True,
        "RATELIMIT_ENABLED": env_bool("RATELIMIT_ENABLED", True),

        # Set to 1 only when running behind a reverse proxy (nginx, Render, ...)
        "TRUST_PROXY": env_bool("TRUST_PROXY", False),

        # Template changes show up without a restart while developing.
        "TEMPLATES_AUTO_RELOAD": environment != "production",

        "APP_VERSION": APP_VERSION,
    }
