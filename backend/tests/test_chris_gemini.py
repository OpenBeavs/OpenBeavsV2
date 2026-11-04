"""Mocked checks for the standalone Gemini capability; no live API calls."""

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.chris import gemini
from app.config import ConfigError


@pytest.fixture
def sdk(monkeypatch):
    """Replace credentials and the provider SDK with local mocks."""
    config = {"GEMINI_API_KEY": "mock-api-key", "CHRIS_MODEL": "models/mock-model"}
    monkeypatch.setattr(gemini, "require_env", config.__getitem__)
    async_client = MagicMock()
    async_client.models.generate_content = AsyncMock(
        return_value=SimpleNamespace(text=" Mock answer. ")
    )
    client = MagicMock()
    client.__enter__.return_value.aio.__aenter__.return_value = async_client
    factory = MagicMock(return_value=client)
    monkeypatch.setattr(gemini.genai, "Client", factory)
    return async_client, factory


def test_answer_passes_history_message_and_system_instruction(sdk):
    """Keep earlier turns ordered and append the current user message once."""
    client, factory = sdk
    result = asyncio.run(
        gemini.answer(
            " New question ",
            [
                {"role": "user", "content": "Earlier question"},
                {"role": "assistant", "content": "Earlier answer"},
            ],
        )
    )
    assert result == "Mock answer."
    request = client.models.generate_content.call_args.kwargs
    assert request["model"] == "mock-model"
    assert [content.role for content in request["contents"]] == [
        "user",
        "model",
        "user",
    ]
    assert [content.parts[0].text for content in request["contents"]] == [
        "Earlier question",
        "Earlier answer",
        "New question",
    ]
    assert request["config"].system_instruction == gemini.SYSTEM_INSTRUCTION
    options = factory.call_args.kwargs["http_options"]
    assert options.timeout == gemini.TIMEOUT_SECONDS * 1000
    assert options.retry_options.attempts == 1


def test_answer_without_history(sdk):
    """History is optional for a one-message request."""
    client, _ = sdk
    assert asyncio.run(gemini.answer("Hello")) == "Mock answer."
    assert len(client.models.generate_content.call_args.kwargs["contents"]) == 1


@pytest.mark.parametrize("text", [None, "", "   "])
def test_empty_model_reply_is_unavailable(text, sdk):
    client, _ = sdk
    client.models.generate_content.return_value = SimpleNamespace(text=text)
    with pytest.raises(gemini.GeminiUnavailable):
        asyncio.run(gemini.answer("Hello"))


@pytest.mark.parametrize(
    "failure", [RuntimeError("private provider details"), TimeoutError()]
)
def test_provider_failure_is_sanitized(failure, sdk):
    client, _ = sdk
    client.models.generate_content.side_effect = failure
    with pytest.raises(gemini.GeminiUnavailable) as error:
        asyncio.run(gemini.answer("Hello"))
    assert str(error.value) == "Gemini is temporarily unavailable."
    assert error.value.__suppress_context__


def test_missing_configuration_does_not_create_provider_client(sdk, monkeypatch):
    _, factory = sdk

    def missing(name):
        raise ConfigError(f"{name} is not set.")

    monkeypatch.setattr(gemini, "require_env", missing)
    with pytest.raises(ConfigError):
        asyncio.run(gemini.answer("Hello"))
    factory.assert_not_called()


def test_blank_input_does_not_call_provider(sdk):
    _, factory = sdk
    with pytest.raises(ValueError, match="non-empty"):
        asyncio.run(gemini.answer("   "))
    factory.assert_not_called()
