"""Application Services' environment holds its own code and no other system's.

Application Services is its own package, installed into its own environment, so that
code here which imported the Conversation Agent or the Agent Registry would fail at
once instead of waiting for a reviewer to notice. These tests run in that environment
and check that the other packages cannot be found from it: the Conversation Agent, the
Agent Registry, and the ``app`` package that held all three before they were separated.
"""

import importlib.util

import pytest


def test_the_application_services_package_is_importable() -> None:
    assert importlib.util.find_spec("application_services") is not None


@pytest.mark.parametrize(
    "package", ["conversation_agent", "agent_registry", "app"]
)
def test_another_system_cannot_be_imported(package: str) -> None:
    assert importlib.util.find_spec(package) is None, (
        f"{package} is importable in Application Services' environment."
    )
