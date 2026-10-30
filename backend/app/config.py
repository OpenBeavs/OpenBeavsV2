"""Environment-based configuration.

Values are read from the process environment (uvicorn loads ``backend/.env``
when started with ``--env-file .env``). Nothing is hardcoded, and values are
read at call time so a missing variable produces a clear error on the request
instead of crashing the server at import.
"""

import os
from pathlib import Path

from dotenv import load_dotenv

# Load local backend/.env automatically if present
_env_path = Path(__file__).resolve().parent.parent / ".env"
load_dotenv(_env_path)
load_dotenv()


class ConfigError(RuntimeError):
    """Raised when a required environment variable is missing or empty."""


def require_env(name: str) -> str:
    """Return the value of environment variable ``name``.

    Raises:
        ConfigError: If the variable is unset or blank. The message names the
            variable only, never its value.
    """
    value = os.environ.get(name, "").strip()
    if not value:
        raise ConfigError(f"{name} is not set. Add it to backend/.env.")
    return value


def env_flag(name: str) -> bool:
    """Return True if environment variable ``name`` is "1", "true" or "yes"."""
    return os.environ.get(name, "").strip().lower() in {"1", "true", "yes"}


def get_env(name: str, default: str = "") -> str:
    """Return the value of environment variable ``name`` or ``default``."""
    return os.environ.get(name, default).strip()


def get_database_url() -> str:
    """Return the configured DATABASE_URL or default to local SQLite."""
    return get_env("DATABASE_URL", "sqlite:///./openbeavs.db")
