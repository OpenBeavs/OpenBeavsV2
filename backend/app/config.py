"""Environment-based configuration.

Values are read from the process environment (uvicorn loads ``backend/.env``
when started with ``--env-file .env``). Nothing is hardcoded, and values are
read at call time so a missing variable produces a clear error on the request
instead of crashing the server at import.
"""

import os


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
