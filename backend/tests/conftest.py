"""Shared fixtures for the backend tests."""

import pytest


@pytest.fixture(autouse=True)
def legacy_chris_fallback(monkeypatch: pytest.MonkeyPatch) -> None:
    """Run the tests as Chris's *fallback* mode (``CHRIS_SELECTION_ONLY=false``).

    Keep these tests independent of local environment overrides. Integration tests
    explicitly enable selection-only mode when inspecting registry outcomes.
    """
    monkeypatch.setenv("CHRIS_SELECTION_ONLY", "false")
