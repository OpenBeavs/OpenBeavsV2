"""The Agent Registry's environment holds the registry and no other system's code.

The registry is its own package, installed into its own environment, so that code here
which imported the Chat System would fail at once instead of waiting for a reviewer to
notice. These tests run in that environment and check that the Chat System's packages
cannot be found from it: Application Services, the Conversation Agent, and the ``app``
package that held all three systems before they were separated.
"""

import importlib.util

import pytest


def test_the_registry_package_is_importable() -> None:
    assert importlib.util.find_spec("agent_registry") is not None


@pytest.mark.parametrize(
    "package", ["application_services", "conversation_agent", "app"]
)
def test_another_system_cannot_be_imported(package: str) -> None:
    assert importlib.util.find_spec(package) is None, (
        f"{package} is importable in the registry's environment."
    )
