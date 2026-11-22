"""Environment-based configuration for the Agent Registry.

Values are read from the process environment. A ``.env`` file, when one exists, is
loaded first: python-dotenv searches upward from this package's folder, so it finds
the ``.env`` at the repository root, and a ``.env`` beside this package's
``pyproject.toml`` would take its place. Variables already set in the process win.
Nothing is hardcoded, and values are read at call time, so a missing variable
produces a clear error on the request instead of crashing the server at import.
"""

import os

from dotenv import load_dotenv

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
        raise ConfigError(f"{name} is not set. Add it to .env.")
    return value


def env_flag(name: str) -> bool:
    """Return True if environment variable ``name`` is "1", "true" or "yes"."""
    return os.environ.get(name, "").strip().lower() in {"1", "true", "yes"}


def get_env(name: str, default: str = "") -> str:
    """Return the value of environment variable ``name`` or ``default``."""
    return os.environ.get(name, default).strip()


def get_database_url() -> str:
    """Return the configured DATABASE_URL or default to local SQLite.

    The default file is relative to the folder the process starts in, so a registry
    started from ``agent-registry/`` uses ``agent-registry/openbeavs.db``.
    """
    return get_env("DATABASE_URL", "sqlite:///./openbeavs.db")
