"""Shared fixtures for the backend tests."""

import pytest


@pytest.fixture(autouse=True)
def legacy_chris_fallback(monkeypatch: pytest.MonkeyPatch) -> None:
    """Run the tests as Chris's *fallback* mode (``CHRIS_SELECTION_ONLY=false``).

    The default is selection-only (no Gemini answer, failures stay visible), which
    ``tests/integration`` and ``tests/test_chris_selection_only.py`` cover. The older
    tests here check the Gemini fallback path, which is still available behind this flag.
    """
    monkeypatch.setenv("CHRIS_SELECTION_ONLY", "false")
