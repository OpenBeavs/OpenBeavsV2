"""Chat -> Chris -> registry, using the real implementations and a fake model.

Each test sends a question the way the frontend does (``POST /chat/message``) and checks
the structured ``routing`` result that comes back. The pipeline stops at the selection:
no test calls an expert, and none treats a selection as an answer.
"""

import asyncio
import json
import time

import httpx
import pytest
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session

from app.chris import gemini
from app.history import bounded_history
from app.models import Agent, Message
from scripts import registry_a2a_client

from .conftest import Pipeline, reply, slow


def routing_of(response: httpx.Response) -> dict:
    assert response.status_code == 200, response.text
    return response.json()["routing"]


class TestSuccessfulSelection:
    def test_the_selected_expert_comes_back_structured(self, experts: Pipeline) -> None:
        experts.choose("math-expert", 0.93, "Arithmetic question.")
        body = experts.ask("What is 15% of 240?").json()

        assert body["routing"] == {
            "status": "selected",
            "agent": {
                "id": "math-expert",
                "name": "Math Expert",
                "description": "Arithmetic and percentages.",
            },
            "confidence": None,
            "reason": None,
            "error": None,
        }

    def test_it_is_a_selection_not_an_answer(self, experts: Pipeline) -> None:
        experts.choose("math-expert")
        body = experts.ask("What is 15% of 240?").json()
        assert "not an answer" in body["response"]
        assert "No expert has been called" in body["response"]
        assert "36" not in body["response"]  # nothing pretends to be the expert's work

    def test_the_older_flat_fields_mirror_the_selection(
        self, experts: Pipeline
    ) -> None:
        experts.choose("osu-expert", 0.88, "About OSU.")
        body = experts.ask("Tell me about OSU housing").json()
        assert body["routed_to"] == "osu-expert"
        assert body["agent_name"] == "Osu Expert"
        # the registry no longer sends a confidence or a reason, so there are none
        assert body["routing_confidence"] is None
        assert body["routing_reason"] is None

    def test_the_expert_endpoint_never_reaches_the_browser(
        self, experts: Pipeline
    ) -> None:
        experts.choose("math-expert")
        text = experts.ask("What is 2+2?").text
        assert "example.test" not in text and "endpoint" not in text

    def test_only_eligible_experts_are_offered_to_the_model(
        self, experts: Pipeline
    ) -> None:
        experts.ask("anything")
        system = experts.prompts[0][0]
        assert "math-expert" in system and "osu-expert" in system
        assert "revoked-expert" not in system

    def test_the_decision_is_stored_with_the_turn(self, experts: Pipeline) -> None:
        experts.choose("math-expert", 0.9, "Math.")
        body = experts.ask("What is 2+2?").json()
        with experts.factory() as db:
            stored = (
                db.query(Message)
                .filter(
                    Message.chat_id == body["chat_id"], Message.sender_type == "agent"
                )
                .one()
            )
        assert stored.meta["routing"]["status"] == "selected"
        assert stored.meta["routing"]["agent"]["id"] == "math-expert"
        # a selection is not a conversation with that expert
        with experts.factory() as db:
            from app.models import Chat

            assert db.get(Chat, body["chat_id"]).agent_id is None


class TestConversationHistory:
    def test_earlier_turns_reach_the_registry_model(self, experts: Pipeline) -> None:
        experts.choose("none", 0.9, "ok")
        first = experts.ask("My name is Sam and I study physics").json()
        experts.ask("What courses should I take?", chat_id=first["chat_id"])

        user_prompt = experts.prompts[1][1]
        assert "Earlier in this conversation" in user_prompt
        assert "user: My name is Sam and I study physics" in user_prompt
        # Chat stores Chris's reply, so it is replayed as the assistant's turn
        assert "assistant: The registry found no registered expert" in user_prompt
        assert (
            "Latest question (select an agent for this):\nWhat courses" in user_prompt
        )

    def test_client_supplied_history_is_used_for_a_new_chat(
        self, experts: Pipeline
    ) -> None:
        experts.ask(
            "And the second one?",
            history=[
                {"role": "user", "content": "Tell me about OSU engineering"},
                {"role": "assistant", "content": "OSU has many programs."},
            ],
        )
        user_prompt = experts.prompts[0][1]
        assert "user: Tell me about OSU engineering" in user_prompt
        assert "assistant: OSU has many programs." in user_prompt

    def test_a_first_message_sends_no_history_section(self, experts: Pipeline) -> None:
        experts.ask("Hello")
        assert experts.prompts[0][1] == "Hello"

    def test_only_recent_turns_are_used(self, experts: Pipeline) -> None:
        history = [
            {"role": "user" if i % 2 == 0 else "assistant", "content": f"turn {i}"}
            for i in range(20)
        ]
        experts.ask("next", history=history)
        prompt = experts.prompts[0][1]
        assert "turn 19" in prompt and "turn 0" not in prompt

    def test_history_goes_in_a_data_part_the_registry_accepts(
        self, experts: Pipeline, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Chris sends the documented contract, not the metadata bridge."""
        seen: list[dict] = []
        original = httpx.AsyncClient.send

        async def spy(self, request, **kwargs):
            if request.method == "POST" and "registry" in str(request.url):
                seen.append(json.loads(request.content))
            return await original(self, request, **kwargs)

        monkeypatch.setattr(httpx.AsyncClient, "send", spy)
        experts.ask("again", history=[{"role": "user", "content": "before"}])
        params = seen[0]["params"]
        parts = params["message"]["parts"]
        assert parts[0] == {"text": "again"}
        assert parts[1]["data"] == {"history": [{"role": "user", "content": "before"}]}
        assert "history" not in params.get("metadata", {})


class TestNoMatch:
    def test_none_is_shown_as_no_match_not_an_answer(self, experts: Pipeline) -> None:
        experts.choose("none", 0.9, "A greeting.")
        body = experts.ask("hi there").json()
        assert body["routing"]["status"] == "no_match"
        assert body["routing"]["agent"] is None
        assert body["routing"]["reason"] is None
        assert body["routed_to"] is None
        assert "no registered expert" in body["response"]

    def test_a_low_confidence_pick_is_no_match(self, experts: Pipeline) -> None:
        experts.choose("math-expert", 0.4, "Maybe.")
        assert routing_of(experts.ask("hmm"))["status"] == "no_match"

    def test_an_empty_registry_is_no_match_and_asks_no_model(
        self, pipeline: Pipeline
    ) -> None:
        body = pipeline.ask("anything").json()
        assert body["routing"]["status"] == "no_match"
        assert pipeline.prompts == []

    def test_no_match_is_not_replaced_by_a_gemini_answer(
        self, experts: Pipeline, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        async def boom(*args):
            raise AssertionError("Gemini must not answer in selection-only mode")

        monkeypatch.setattr(gemini, "answer", boom)
        assert routing_of(experts.ask("hi"))["status"] == "no_match"


class TestRegistryErrorsAreVisible:
    @pytest.mark.parametrize(
        ("raises", "code", "retryable"),
        [
            ("llm", "selection_unavailable", True),
            ("config", "not_configured", False),
            ("garbage", "invalid_model_reply", True),
        ],
    )
    def test_registry_reported_errors_keep_their_code_and_source(
        self, experts: Pipeline, raises: str, code: str, retryable: bool
    ) -> None:
        from app.config import ConfigError
        from app.registry.llm import LLMError

        async def model(system, user, schema):
            if raises == "llm":
                raise LLMError("HTTP 503")
            if raises == "config":
                raise ConfigError("REGISTRY_MODEL is not set.")
            return "this is not json"

        experts.set_model(model)
        body = experts.ask("question").json()
        assert body["routing"]["status"] == "error"
        assert body["routing"]["error"] == {
            "code": code,
            "retryable": retryable,
            "source": "registry",
        }
        assert body["routing"]["agent"] is None and body["routed_to"] is None
        assert code in body["response"]

    def test_errors_are_not_turned_into_a_gemini_answer(
        self, experts: Pipeline, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        async def boom(*args):
            raise AssertionError("Gemini must not answer in selection-only mode")

        monkeypatch.setattr(gemini, "answer", boom)

        async def failing(system, user, schema):
            raise RuntimeError("model blew up")

        experts.set_model(failing)
        error = routing_of(experts.ask("q"))["error"]
        assert error["code"] == "internal_error" and error["source"] == "registry"

    def test_the_model_error_text_never_reaches_the_browser(
        self, experts: Pipeline
    ) -> None:
        async def failing(system, user, schema):
            raise RuntimeError("SECRET-INTERNAL-DETAIL")

        experts.set_model(failing)
        assert "SECRET-INTERNAL-DETAIL" not in experts.ask("q").text

    def test_a_database_failure_in_the_registry_is_reported(
        self, experts: Pipeline, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from sqlalchemy.exc import OperationalError

        from app.registry import a2a

        def broken(factory):
            raise OperationalError("select", {}, Exception("db down"))

        monkeypatch.setattr(a2a, "load_candidates", broken)
        error = routing_of(experts.ask("q"))["error"]
        assert error == {
            "code": "registry_unavailable",
            "retryable": True,
            "source": "registry",
        }

    def test_too_many_experts_is_a_visible_non_retryable_error(
        self, pipeline: Pipeline
    ) -> None:
        for i in range(51):
            pipeline.add_agent(f"expert-{i:02}")
        error = routing_of(pipeline.ask("q"))["error"]
        assert error["code"] == "registry_capacity_exceeded"
        assert error["retryable"] is False and error["source"] == "registry"
        assert pipeline.prompts == []


class TestAnAgentBecomingIneligibleDuringSelection:
    @pytest.mark.parametrize(
        "change",
        [
            {"status": "revoked", "is_active": False},
            {"is_active": False},
            {"trust_tier": "privileged"},
        ],
    )
    def test_it_is_not_returned_as_selected(
        self, experts: Pipeline, change: dict
    ) -> None:
        async def model(system, user, schema):
            experts.update_agent("math-expert", **change)  # revoked mid-selection
            return reply("math-expert", 0.97, "Arithmetic.")

        experts.set_model(model)
        body = experts.ask("What is 2+2?").json()
        assert body["routing"]["status"] == "error"
        assert body["routing"]["error"] == {
            "code": "agent_unavailable",
            "retryable": True,
            "source": "registry",
        }
        assert body["routing"]["agent"] is None and body["routed_to"] is None
        assert "Math Expert" not in body["response"]

    def test_a_later_question_no_longer_offers_the_revoked_expert(
        self, experts: Pipeline
    ) -> None:
        experts.update_agent("math-expert", status="revoked", is_active=False)
        experts.ask("q")
        assert "math-expert" not in experts.prompts[0][0]


class TestRegistryTimeouts:
    def test_a_slow_registry_is_reported_as_a_timeout(
        self, experts: Pipeline, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("REGISTRY_A2A_TIMEOUT_SECONDS", "1")
        experts.registry_delay = 3  # the registry's reply takes 3 s; Chris waits 1 s
        started = time.monotonic()
        error = routing_of(experts.ask("q"))["error"]
        assert time.monotonic() - started < 2.5  # Chris gave up at its own deadline
        assert error == {
            "code": "registry_timeout",
            "retryable": True,
            "source": "chris",
        }

    def test_slow_but_within_the_deadline_still_succeeds(
        self, experts: Pipeline, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("REGISTRY_A2A_TIMEOUT_SECONDS", "5")
        experts.set_model(slow(0.6, reply("math-expert", 0.9, "Math.")))
        assert routing_of(experts.ask("q"))["status"] == "selected"

    def test_registry_overload_is_a_retryable_error_not_a_hang(
        self, experts: Pipeline
    ) -> None:
        """When the registry's model slots are exhausted it answers selection_busy
        (the limiter itself is tested in tests/registry/test_limits.py)."""
        from app.registry.llm import ModelBusyError

        async def busy(system, user, schema):
            raise ModelBusyError

        experts.set_model(busy)
        error = routing_of(experts.ask("q"))["error"]
        assert error == {
            "code": "selection_busy",
            "retryable": True,
            "source": "registry",
        }


class TestChatDeadline:
    def test_chris_taking_too_long_is_a_503_with_a_fixed_message(
        self, experts: Pipeline, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from app.chris import registry_client

        async def stuck(message, history):
            await asyncio.sleep(5)

        monkeypatch.setattr(registry_client, "select_agent", stuck)
        monkeypatch.setenv("CHRIS_A2A_TIMEOUT_SECONDS", "1")
        started = time.monotonic()
        response = experts.ask("q")
        assert time.monotonic() - started < 3
        assert response.status_code == 503
        assert response.json()["detail"] == (
            "Chris is temporarily unavailable. Please try again shortly."
        )

    def test_the_deadlines_nest_correctly_by_default(self) -> None:
        from app.chat import a2a_client
        from app.chris import registry_client
        from app.registry import llm

        registry_worst_case = 2 + llm.request_timeout()  # configured: 2 s queue + 8 s
        assert registry_client.DEFAULT_TIMEOUT_SECONDS > 2 + 8
        assert (
            a2a_client.DEFAULT_TIMEOUT_SECONDS > registry_client.DEFAULT_TIMEOUT_SECONDS
        )
        assert a2a_client.DEFAULT_TIMEOUT_SECONDS < 90  # the browser's deadline
        assert registry_worst_case > 0 and llm.DEFAULT_WAIT_SECONDS > 0


class TestChatLooksUpWhatTheRegistryNoLongerSends:
    """The registry names only the expert's id; Chat reads the display fields itself."""

    def test_name_and_description_come_from_the_database(
        self, experts: Pipeline
    ) -> None:
        experts.choose("math-expert")
        experts.update_agent("math-expert", name="Math Wizard", description="Numbers.")
        body = experts.ask("What is 2+2?").json()
        assert body["routing"]["agent"] == {
            "id": "math-expert",
            "name": "Math Wizard",
            "description": "Numbers.",
        }
        assert "Math Wizard" in body["response"] and "not an answer" in body["response"]
        assert body["agent_name"] == "Math Wizard"

    def test_the_stored_assistant_turn_uses_the_looked_up_name(
        self, experts: Pipeline
    ) -> None:
        experts.choose("math-expert")
        body = experts.ask("What is 2+2?").json()
        with experts.factory() as db:
            stored = (
                db.query(Message)
                .filter(
                    Message.chat_id == body["chat_id"], Message.sender_type == "agent"
                )
                .one()
            )
        assert "Math Expert" in stored.content
        assert stored.meta["routing"]["agent"]["name"] == "Math Expert"

    def test_an_id_this_database_does_not_know_still_shows_as_a_selection(
        self, experts: Pipeline, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """If Chat cannot find the record (a different database), the id is the name."""
        from app.chat import service

        class WithoutAgents:
            """A session that behaves normally except that it finds no agent rows."""

            def __init__(self, db):
                self.db = db

            def get(self, model_cls, key):
                return (
                    None
                    if model_cls is service.DBAgent
                    else self.db.get(model_cls, key)
                )

            def __getattr__(self, name):
                return getattr(self.db, name)

        real = service.handle_message

        async def handle(form, db):
            return await real(form, WithoutAgents(db))

        monkeypatch.setattr(service, "handle_message", handle)

        experts.choose("math-expert")
        body = experts.ask("What is 2+2?").json()
        assert body["routing"]["status"] == "selected"
        assert body["routing"]["agent"]["name"] == "math-expert"

    def test_no_confidence_or_reason_reaches_the_browser(
        self, experts: Pipeline
    ) -> None:
        experts.choose("math-expert", 0.97, "SECRET-REASON from the model")
        text = experts.ask("What is 2+2?").text
        assert "SECRET-REASON" not in text and "0.97" not in text


@pytest.mark.parametrize(
    "content",
    ["x" * 4000, "😀" * 4000, "\x00" * 4000],
    ids=["ascii", "unicode", "controls"],
)
def test_large_history_fits_registry_before_it_is_parsed(experts, monkeypatch, content):
    seen = []
    original = httpx.AsyncClient.send

    async def capture(self, request, **kwargs):
        if request.method == "POST" and "registry" in str(request.url):
            seen.append(len(request.content))
        return await original(self, request, **kwargs)

    monkeypatch.setattr(httpx.AsyncClient, "send", capture)
    response = experts.ask(
        "next", history=[{"role": "user", "content": content} for _ in range(24)]
    )
    assert response.status_code == 200
    assert response.json()["routing"]["status"] == "no_match"
    assert seen and max(seen) < 64 * 1024
    assert experts.prompts


def test_history_truncation_keeps_valid_utf8_and_recent_turns():
    history = [{"role": "user", "content": str(i) + "😀" * 1000} for i in range(12)]
    bounded = bounded_history(history)
    assert len(bounded) == 6 and bounded[0]["content"].startswith("6")
    assert all(len(t["content"].encode("utf-8")) <= 1000 for t in bounded)


def test_oversized_question_is_rejected_before_a2a(experts):
    response = experts.ask("😀" * 1001)
    assert response.status_code == 422
    assert not experts.prompts


def test_display_database_failure_preserves_successful_selection(experts, monkeypatch):
    experts.choose("math-expert")
    original = Session.get

    def get(self, entity, *args, **kwargs):
        if entity is Agent:
            raise OperationalError("display lookup", {}, RuntimeError("unavailable"))
        return original(self, entity, *args, **kwargs)

    monkeypatch.setattr(Session, "get", get)
    response = experts.ask("math")
    assert response.status_code == 200
    assert response.json()["routing"]["agent"]["id"] == "math-expert"
    assert response.json()["routing"]["status"] == "selected"


def test_cli_reads_the_registry_text_contract(experts, monkeypatch):
    from app.chris import registry_client

    async def create(url, config):
        from a2a.client import ClientFactory

        http = registry_client._http_client(14)
        return await ClientFactory(
            type(config)(httpx_client=http, streaming=False)
        ).create_from_url(url)

    monkeypatch.setattr(registry_a2a_client, "create_client", create)
    result = asyncio.run(
        registry_a2a_client.ask("http://registry.test/a2a/registry", "hi", None)
    )
    assert json.dumps(result) == '{"agent": "none"}'
