"""Authentication and Single Sign-On (SSO) module for OpenBeavs.

Supports OSU Microsoft Entra ID (OIDC), local dev mock authentication,
and FastAPI route-level authorization dependencies.
"""

from application_services.auth.dependencies import (
    get_current_user,
    get_optional_user,
    require_elevated_user,
    require_role,
)
from application_services.auth.router import router

__all__ = [
    "get_current_user",
    "get_optional_user",
    "require_elevated_user",
    "require_role",
    "router",
]

