"""The Conversation Agent's environment holds the agent and no other system's code.

The agent is its own package, installed into its own environment, so that code here
which imported Application Services or the Agent Registry would fail at once instead
of waiting for a reviewer to notice. These tests run in that environment and check
that the other packages cannot be found from it: Application Services, the Agent
Registry, and the ``app`` package that held all three before they were separated.
"""

import importlib.util

import pytest


def test_the_agent_package_is_importable() -> None:
    assert importlib.util.find_spec("conversation_agent") is not None


@pytest.mark.parametrize(
    "package", ["application_services", "agent_registry", "app"]
)
def test_another_system_cannot_be_imported(package: str) -> None:
    assert importlib.util.find_spec(package) is None, (
        f"{package} is importable in the agent's environment."
    )
