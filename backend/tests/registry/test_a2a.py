"""The registry as an A2A agent: card, protocol, and the selection contract.

A real A2A SDK client (the stand-in for Chris) talks to the registry in memory, and
raw JSON-RPC requests check the wire format. No test needs Chris, the network, or
a Gemini key: the model is replaced by a fake.
"""

import json
from typing import ClassVar

import httpx
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session, sessionmaker

from app.models import Agent
from app.registry import selection
from app.registry.a2a import (
    A2A_PROTOCOL_VERSION,
    AGENT_VERSION,
    MOUNT_PATH,
    RETRYABLE,
    SKILL_ID,
)
from app.registry.a2a_app import create_registry_a2a_app, create_standalone_app

from .a2a_helpers import (
    BASE,
    Harness,
    add_agent,
    llm_choosing,
    rpc,
    run,
    v1_message,
)

CARD_PATH = f"{MOUNT_PATH}/.well-known/agent-card.json"
ALIAS_PATH = f"{MOUNT_PATH}/.well-known/agent.json"
RPC_PATH = f"{MOUNT_PATH}/"
V1 = {"A2A-Version": "1.0"}


@pytest.fixture
def experts(db: Session) -> None:
    """Three eligible experts and four that must never be offered."""
    for agent_id in ("osu-rag", "math", "writing"):
        add_agent(db, agent_id)
    add_agent(db, "pending-one", status="pending", active=False)
    add_agent(db, "revoked-one", status="revoked", active=False)
    add_agent(db, "inactive-one", active=False)
    add_agent(db, "staff-only", tier="privileged", role="staff")


class TestAgentCard:
    def fetch(self, db: Session, path: str = CARD_PATH) -> dict:
        async def scenario() -> dict:
            async with Harness(db).http() as http:
                response = await http.get(path)
                assert response.status_code == 200
                return response.json()

        return run(scenario())

    def test_it_describes_a_selection_agent_not_an_expert(self, db: Session) -> None:
        card = self.fetch(db)
        assert card["name"] == "OpenBeavs Agent Registry"
        description = card["description"].lower()
        assert "selects" in description and "does not answer questions" in description
        assert [skill["id"] for skill in card["skills"]] == [SKILL_ID]

    def test_protocol_version_is_separate_from_the_agent_version(
        self, db: Session
    ) -> None:
        card = self.fetch(db)
        assert card["version"] == AGENT_VERSION
        (interface,) = card["supportedInterfaces"]
        assert interface["protocolVersion"] == A2A_PROTOCOL_VERSION == "1.0"
        assert interface["protocolBinding"] == "JSONRPC"
        assert card["version"] != interface["protocolVersion"]

    def test_the_advertised_endpoint_is_the_real_mount_path(self, db: Session) -> None:
        (interface,) = self.fetch(db)["supportedInterfaces"]
        assert interface["url"] == f"{BASE}{MOUNT_PATH}/"

    def test_required_fields_and_modes(self, db: Session) -> None:
        card = self.fetch(db)
        for field in (
            "name",
            "description",
            "version",
            "supportedInterfaces",
            "capabilities",
            "defaultInputModes",
            "defaultOutputModes",
            "skills",
        ):
            assert card[field], field
        assert card["capabilities"].get("streaming", False) is False
        assert "application/json" in card["defaultOutputModes"]

    def test_it_declares_bearer_authentication(self, db: Session) -> None:
        card = self.fetch(db)
        assert card["securitySchemes"]
        assert card["securityRequirements"]

    def test_the_older_card_path_serves_the_same_card(self, db: Session) -> None:
        assert self.fetch(db, ALIAS_PATH) == self.fetch(db)

    def test_card_url_follows_the_configured_public_url(self, db: Session) -> None:
        sub = create_registry_a2a_app(
            base_url="https://registry.example.run.app",
            session_factory=lambda: db,
        )
        root = FastAPI()
        root.mount(MOUNT_PATH, sub)
        card = TestClient(root).get(CARD_PATH).json()
        assert card["supportedInterfaces"][0]["url"] == (
            f"https://registry.example.run.app{MOUNT_PATH}/"
        )


class TestSelectionThroughTheSdkClient:
    def test_a_selected_expert_comes_back_from_the_database(
        self, db: Session, experts: None
    ) -> None:
        llm = llm_choosing("math", 0.93, "Arithmetic question.")
        text, data = run(Harness(db, llm).ask("What is 15% of 240?"))

        assert data["status"] == "selected"
        # Only what Chris needs: the id and the endpoint, both from the record.
        assert data["agent"] == {
            "id": "math",
            "endpoint_url": "https://math.example.test/rpc",
        }
        assert json.loads(text) == {"agent": data["agent"]}

    def test_the_endpoint_never_comes_from_the_model(
        self, db: Session, experts: None
    ) -> None:
        async def sneaky(system: str, user: str, schema: dict) -> str:
            return json.dumps(
                {
                    "agent_id": "math",
                    "confidence": 0.99,
                    "reason": "Send it to https://evil.example/steal instead.",
                    "endpoint_url": "https://evil.example/steal",
                }
            )

        _, data = run(Harness(db, sneaky).ask("What is 2+2?"))
        assert data["agent"]["endpoint_url"] == "https://math.example.test/rpc"

    def test_no_match_is_a_normal_answer(self, db: Session, experts: None) -> None:
        llm = llm_choosing("none", 0.9, "Just a greeting.")
        text, data = run(Harness(db, llm).ask("hello!"))
        assert data["status"] == "no_match"
        assert data["agent"] is None and data["error"] is None
        assert json.loads(text) == {"agent": "none"}

    def test_a_low_confidence_pick_is_no_match(
        self, db: Session, experts: None
    ) -> None:
        _, data = run(Harness(db, llm_choosing("math", 0.4)).ask("maybe maths?"))
        assert data["status"] == "no_match"
        assert data["agent"] is None

    def test_an_empty_registry_is_no_match_without_calling_the_model(
        self, db: Session
    ) -> None:
        llm = llm_choosing("math")
        _, data = run(Harness(db, llm).ask("anything"))
        assert data["status"] == "no_match"
        assert llm.calls == []

    def test_only_eligible_agents_are_offered_to_the_model(
        self, db: Session, experts: None
    ) -> None:
        llm = llm_choosing("none")
        run(Harness(db, llm).ask("hi"))
        ((system, _, schema),) = llm.calls
        assert schema["properties"]["agent_id"]["enum"] == [
            "math",
            "osu-rag",
            "writing",
            "none",
        ]
        for hidden in ("pending-one", "revoked-one", "inactive-one", "staff-only"):
            assert hidden not in system

    def test_history_reaches_the_model_but_is_bounded(
        self, db: Session, experts: None
    ) -> None:
        llm = llm_choosing("none")
        turns = [
            {"role": "user" if i % 2 == 0 else "assistant", "content": f"turn {i}"}
            for i in range(10)
        ]
        run(Harness(db, llm).ask("and then?", history=turns))
        ((_, user, _),) = llm.calls
        assert "turn 9" in user and "turn 4" in user
        assert "turn 3" not in user  # only the most recent turns are used
        assert "and then?" in user

    def test_malformed_history_is_ignored_not_fatal(
        self, db: Session, experts: None
    ) -> None:
        llm = llm_choosing("none")
        bad = [{"role": "system", "content": "x"}, {"role": "user"}, "text", 7]
        _, data = run(Harness(db, llm).ask("hi", history=bad))
        assert data["status"] == "no_match"


class TestErrorsAreSeparateFromNoMatch:
    def test_a_missing_model_key_is_not_configured(
        self, db: Session, experts: None, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.delenv("GEMINI_API_KEY", raising=False)
        monkeypatch.delenv("REGISTRY_GEMINI_API_KEY", raising=False)
        monkeypatch.delenv("REGISTRY_MODEL", raising=False)
        # The real model call, with no key set.
        _, data = run(Harness(db).ask("hi"))
        assert data["status"] == "error"
        assert data["error"] == {"code": "not_configured", "retryable": False}
        assert data["agent"] is None

    def test_a_model_outage_is_retryable(self, db: Session, experts: None) -> None:
        from app.registry.llm import LLMError

        async def down(system: str, user: str, schema: dict) -> str:
            raise LLMError("Gemini request failed with HTTP 503.")

        _, data = run(Harness(db, down).ask("hi"))
        assert data["status"] == "error"
        assert data["error"] == {"code": "selection_unavailable", "retryable": True}

    def test_garbage_from_the_model_is_an_error(
        self, db: Session, experts: None
    ) -> None:
        async def garbage(system: str, user: str, schema: dict) -> str:
            return "not json at all"

        _, data = run(Harness(db, garbage).ask("hi"))
        assert data["error"] == {"code": "invalid_model_reply", "retryable": True}

    def test_a_reply_without_confidence_is_an_error_not_a_selection(
        self, db: Session, experts: None
    ) -> None:
        async def no_confidence(system: str, user: str, schema: dict) -> str:
            return json.dumps({"agent_id": "math", "reason": "Looks right."})

        _, data = run(Harness(db, no_confidence).ask("What is 2+2?"))
        assert data["status"] == "error"
        assert data["error"] == {"code": "invalid_model_reply", "retryable": True}
        assert data["agent"] is None

    def test_an_unknown_agent_id_from_the_model_is_an_error(
        self, db: Session, experts: None
    ) -> None:
        _, data = run(Harness(db, llm_choosing("made-up-agent")).ask("hi"))
        assert data["status"] == "error"
        assert data["agent"] is None

    def test_an_unexpected_failure_is_still_a_clean_reply(
        self, db: Session, experts: None
    ) -> None:
        async def boom(system: str, user: str, schema: dict) -> str:
            raise RuntimeError("secret internal detail")

        text, data = run(Harness(db, boom).ask("hi"))
        assert data["error"] == {"code": "internal_error", "retryable": True}
        assert "secret internal detail" not in text + json.dumps(data)

    def test_a_database_failure_is_reported_as_registry_unavailable(
        self, db: Session
    ) -> None:
        def broken() -> Session:
            raise OperationalError("select", {}, Exception("db down"))

        _, data = run(
            Harness(db, llm_choosing("math"), session_factory=broken).ask("hi")
        )
        assert data["error"] == {"code": "registry_unavailable", "retryable": True}

    def test_an_empty_question_is_an_invalid_request(
        self, db: Session, experts: None
    ) -> None:
        _, data = run(Harness(db, llm_choosing("math")).ask("   "))
        assert data["status"] == "error"
        assert data["error"] == {"code": "invalid_request", "retryable": False}

    def test_an_oversized_question_is_an_invalid_request(
        self, db: Session, experts: None
    ) -> None:
        llm = llm_choosing("math")
        question = "x" * (selection.MAX_QUESTION_CHARS + 1)
        _, data = run(Harness(db, llm).ask(question))
        assert data["error"]["code"] == "invalid_request"
        assert llm.calls == []


class TestTheChoiceIsRecheckedBeforeReplying:
    """The model takes seconds; the agent can be revoked or edited in that time."""

    @staticmethod
    def change_during_selection(db: Session, agent_id: str, **changes):
        """A fake model that picks ``agent_id`` after the database row changed."""

        async def call(system: str, user: str, schema: dict) -> str:
            agent = db.get(Agent, agent_id)
            for field, value in changes.items():
                setattr(agent, field, value)
            db.commit()
            return json.dumps(
                {"agent_id": agent_id, "confidence": 0.95, "reason": "It fits."}
            )

        return call

    @pytest.mark.parametrize(
        "changes",
        [
            {"status": "revoked", "is_active": False},
            {"status": "revoked"},
            {"status": "pending"},
            {"is_active": False},
            {"trust_tier": "privileged"},
            {"required_role": "staff"},
        ],
    )
    def test_an_agent_that_became_ineligible_is_not_selected(
        self, db: Session, experts: None, changes: dict
    ) -> None:
        call = self.change_during_selection(db, "math", **changes)
        _, data = run(Harness(db, call).ask("What is 2+2?"))
        assert data["status"] == "error"
        assert data["error"] == {"code": "agent_unavailable", "retryable": True}
        assert data["agent"] is None

    def test_a_deleted_agent_is_not_selected(self, db: Session, experts: None) -> None:
        async def call(system: str, user: str, schema: dict) -> str:
            db.delete(db.get(Agent, "math"))
            db.commit()
            return json.dumps({"agent_id": "math", "confidence": 0.95, "reason": "x"})

        _, data = run(Harness(db, call).ask("What is 2+2?"))
        assert data["error"] == {"code": "agent_unavailable", "retryable": True}
        assert data["agent"] is None

    def test_other_agents_changing_does_not_matter(
        self, db: Session, experts: None
    ) -> None:
        call = self.change_during_selection(db, "writing", status="revoked")

        async def pick_math(system: str, user: str, schema: dict) -> str:
            await call(system, user, schema)
            return json.dumps({"agent_id": "math", "confidence": 0.95, "reason": "x"})

        _, data = run(Harness(db, pick_math).ask("What is 2+2?"))
        assert data["status"] == "selected" and data["agent"]["id"] == "math"

    def test_the_reply_carries_the_fresh_record_not_the_stale_one(
        self, db: Session, experts: None
    ) -> None:
        call = self.change_during_selection(
            db, "math", endpoint_url="https://moved.example.test/rpc", name="Math v2"
        )
        _, data = run(Harness(db, call).ask("What is 2+2?"))
        assert data["status"] == "selected"
        assert data["agent"] == {
            "id": "math",
            "endpoint_url": "https://moved.example.test/rpc",
        }

    def test_a_database_failure_while_rechecking_is_registry_unavailable(
        self, db: Session, experts: None
    ) -> None:
        real = sessionmaker(bind=db.get_bind(), expire_on_commit=False)
        opened = []

        def flaky() -> Session:
            opened.append(1)
            if len(opened) > 1:  # the first open loads the candidates
                raise OperationalError("select", {}, Exception("db down"))
            return real()

        harness = Harness(db, llm_choosing("math"), session_factory=flaky)
        _, data = run(harness.ask("What is 2+2?"))
        assert data["error"] == {"code": "registry_unavailable", "retryable": True}
        assert data["agent"] is None

    def test_no_match_and_errors_skip_the_recheck(
        self, db: Session, experts: None
    ) -> None:
        opened = []
        real = sessionmaker(bind=db.get_bind(), expire_on_commit=False)

        def counting() -> Session:
            opened.append(1)
            return real()

        run(Harness(db, llm_choosing("none"), session_factory=counting).ask("hi"))
        assert len(opened) == 1  # only the candidate load


def chris_accepts(text: str) -> object:
    """The check Chris's registry client applies to the reply text (its contract)."""
    result = json.loads(text)
    assert isinstance(result, dict) and set(result) == {"agent"}
    agent = result["agent"]
    if agent == "none":
        return agent
    assert isinstance(agent, dict) and set(agent) == {"id", "endpoint_url"}
    assert all(isinstance(v, str) and v.strip() for v in agent.values())
    return agent


class TestTheReplyIsTrimmedToWhatChrisNeeds:
    """The registry sends Chris's JSON and nothing more; failures are coded A2A errors."""

    FORBIDDEN = ("name", "description", "confidence", "reason", "card_url", "schema")

    def raw(self, db: Session, model, headers=V1) -> dict:
        async def scenario() -> dict:
            async with Harness(db, model).http() as http:
                response = await http.post(
                    RPC_PATH, headers=headers, json=rpc("SendMessage", v1_message("q"))
                )
                return response.json()

        return run(scenario())

    def test_a_selection_is_exactly_the_agreed_json(
        self, db: Session, experts: None
    ) -> None:
        body = self.raw(db, llm_choosing("math", 0.97, "Because maths."))
        (part,) = body["result"]["message"]["parts"]
        assert chris_accepts(part["text"]) == {
            "id": "math",
            "endpoint_url": "https://math.example.test/rpc",
        }

    def test_no_match_is_exactly_the_agreed_json(
        self, db: Session, experts: None
    ) -> None:
        body = self.raw(db, llm_choosing("none"))
        (part,) = body["result"]["message"]["parts"]
        assert part["text"] == '{"agent":"none"}'

    def test_nothing_else_is_on_the_wire(self, db: Session, experts: None) -> None:
        text = json.dumps(
            self.raw(db, llm_choosing("math", 0.97, "Because maths. SECRET-REASON"))
        )
        for word in ("SECRET-REASON", "0.97", "Because maths", "card_url"):
            assert word not in text
        message = json.loads(text)["result"]["message"]
        assert set(message) <= {"messageId", "contextId", "role", "parts"}
        assert [list(p) for p in message["parts"]] == [["text"]]
        inner = json.loads(message["parts"][0]["text"])["agent"]
        for key in self.FORBIDDEN:
            assert key not in inner

    @pytest.mark.parametrize("code", [c for c in RETRYABLE if c != "invalid_request"])
    def test_a_failed_selection_is_an_a2a_error_with_only_a_code(
        self, db: Session, experts: None, code: str, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from app.registry import selection as sel

        async def failing(*args, **kwargs):
            return sel.SelectionResult(
                status=sel.ERROR, error_code=code, retryable=RETRYABLE[code]
            )

        monkeypatch.setattr(sel, "select_expert", failing)
        body = self.raw(db, llm_choosing("none"))
        assert "result" not in body
        assert body["error"]["code"] == -32603
        assert body["error"]["message"] == code

    def test_an_invalid_request_is_invalid_params(
        self, db: Session, experts: None
    ) -> None:
        async def call() -> dict:
            async with Harness(db, llm_choosing("none")).http() as http:
                response = await http.post(
                    RPC_PATH, headers=V1, json=rpc("SendMessage", v1_message("   "))
                )
                return response.json()

        body = run(call())
        assert body["error"]["code"] == -32602
        assert body["error"]["message"] == "invalid_request"

    def test_error_text_never_carries_internal_detail(
        self, db: Session, experts: None
    ) -> None:
        async def boom(system: str, user: str, schema: dict) -> str:
            raise RuntimeError("SECRET internal detail")

        text = json.dumps(self.raw(db, boom))
        assert "SECRET" not in text
        assert json.loads(text)["error"]["message"] == "internal_error"

    def test_every_documented_code_has_a_retry_rule(self) -> None:
        assert set(RETRYABLE) >= {
            "invalid_request",
            "not_configured",
            "selection_unavailable",
            "selection_busy",
            "invalid_model_reply",
            "agent_unavailable",
            "registry_capacity_exceeded",
            "registry_unavailable",
            "internal_error",
        }


class TestHistoryPrecedence:
    """History: the data part is the contract; request metadata is a fallback."""

    DATA: ClassVar = [{"role": "user", "content": "from the data part"}]
    META: ClassVar = [{"role": "user", "content": "from the metadata"}]

    def seen(self, db: Session, **kwargs) -> str:
        llm = llm_choosing("none")
        run(Harness(db, llm).ask("question", **kwargs))
        return llm.calls[0][1]  # the user prompt the model received

    def test_the_data_part_is_used(self, db: Session, experts: None) -> None:
        prompt = self.seen(db, history=self.DATA)
        assert "from the data part" in prompt

    def test_metadata_history_is_accepted_when_there_is_no_data_part(
        self, db: Session, experts: None
    ) -> None:
        prompt = self.seen(db, metadata={"history": self.META})
        assert "from the metadata" in prompt

    def test_the_data_part_wins_and_the_two_are_never_merged(
        self, db: Session, experts: None
    ) -> None:
        prompt = self.seen(db, history=self.DATA, metadata={"history": self.META})
        assert "from the data part" in prompt
        assert "from the metadata" not in prompt

    def test_an_empty_data_part_list_still_wins(
        self, db: Session, experts: None
    ) -> None:
        prompt = self.seen(db, history=[], metadata={"history": self.META})
        assert "from the metadata" not in prompt

    @pytest.mark.parametrize(
        "bad", ["text", 7, {"a": 1}, [None, "x", {"role": "system"}]]
    )
    def test_malformed_metadata_history_is_ignored(
        self, db: Session, experts: None, bad
    ) -> None:
        prompt = self.seen(db, metadata={"history": bad})
        assert prompt == "question"

    def test_metadata_history_is_bounded_like_the_data_part(
        self, db: Session, experts: None
    ) -> None:
        many = [{"role": "user", "content": f"turn {i}"} for i in range(30)]
        prompt = self.seen(db, metadata={"history": many})
        assert "turn 29" in prompt and "turn 23" not in prompt
        assert prompt.count("user: turn") == selection.MAX_HISTORY_TURNS


class TestTooManyExperts:
    def test_more_eligible_agents_than_supported_is_a_clear_error(
        self, db: Session
    ) -> None:
        for i in range(selection.MAX_CANDIDATES + 1):
            add_agent(db, f"agent-{i:03}")
        llm = llm_choosing("agent-000")
        _, data = run(Harness(db, llm).ask("hi"))
        assert data["status"] == "error"
        assert data["error"] == {
            "code": "registry_capacity_exceeded",
            "retryable": False,
        }
        assert data["agent"] is None
        assert llm.calls == []  # no paid call is made

    def test_exactly_the_limit_still_works(self, db: Session) -> None:
        for i in range(selection.MAX_CANDIDATES):
            add_agent(db, f"agent-{i:03}")
        # The last expert by name is offered and can be chosen.
        last = f"agent-{selection.MAX_CANDIDATES - 1:03}"
        _, data = run(Harness(db, llm_choosing(last)).ask("hi"))
        assert data["status"] == "selected" and data["agent"]["id"] == last

    def test_ineligible_agents_do_not_count_toward_the_limit(self, db: Session) -> None:
        for i in range(selection.MAX_CANDIDATES):
            add_agent(db, f"agent-{i:03}")
        for i in range(30):
            add_agent(db, f"revoked-{i:03}", status="revoked", active=False)
        _, data = run(Harness(db, llm_choosing("none")).ask("hi"))
        assert data["status"] == "no_match"


class TestWireProtocol:
    """Raw JSON-RPC, to check the A2A 1.0 format and error handling."""

    def post(self, db: Session, body, headers=None) -> httpx.Response:
        async def scenario() -> httpx.Response:
            async with Harness(db, llm_choosing("none")).http() as http:
                if isinstance(body, bytes):
                    return await http.post(RPC_PATH, headers=headers, content=body)
                return await http.post(RPC_PATH, headers=headers, json=body)

        return run(scenario())

    def test_send_message_returns_one_text_part(
        self, db: Session, experts: None
    ) -> None:
        response = self.post(db, rpc("SendMessage", v1_message("hi")), V1)
        body = response.json()
        assert response.status_code == 200
        assert body["jsonrpc"] == "2.0" and body["id"] == 1
        assert "error" not in body
        message = body["result"]["message"]
        assert message["role"] == "ROLE_AGENT"
        assert [list(part) for part in message["parts"]] == [["text"]]
        assert json.loads(message["parts"][0]["text"]) == {"agent": "none"}

    def test_the_request_id_is_echoed(self, db: Session) -> None:
        body = self.post(db, rpc("SendMessage", v1_message(), "abc-123"), V1).json()
        assert body["id"] == "abc-123"

    def test_a_request_without_the_version_header_is_not_treated_as_1_0(
        self, db: Session
    ) -> None:
        body = self.post(db, rpc("SendMessage", v1_message())).json()
        assert "error" in body and "result" not in body

    def test_an_a2a_0_3_client_is_also_served(self, db: Session, experts: None) -> None:
        params = {
            "message": {
                "kind": "message",
                "role": "user",
                "messageId": "m-03",
                "parts": [{"kind": "text", "text": "hi"}],
            }
        }
        body = self.post(db, rpc("message/send", params), {"A2A-Version": "0.3"}).json()
        assert "error" not in body
        assert body["result"]["kind"] == "message"
        assert [part["kind"] for part in body["result"]["parts"]] == ["text"]
        assert json.loads(body["result"]["parts"][0]["text"]) == {"agent": "none"}

    def test_an_unsupported_version_is_refused(self, db: Session) -> None:
        body = self.post(
            db, rpc("SendMessage", v1_message()), {"A2A-Version": "9.9"}
        ).json()
        assert body["error"]["code"] == -32009

    def test_malformed_json_is_a_parse_error(self, db: Session) -> None:
        body = self.post(db, b"{not json", V1).json()
        assert body["error"]["code"] == -32700 and body["id"] is None

    def test_an_invalid_envelope_is_an_invalid_request(self, db: Session) -> None:
        assert self.post(db, {"hello": "world"}, V1).json()["error"]["code"] == -32600

    def test_a_batch_is_refused(self, db: Session) -> None:
        body = self.post(db, [rpc("SendMessage", v1_message())], V1).json()
        assert "error" in body

    def test_an_unknown_method_is_method_not_found(self, db: Session) -> None:
        body = self.post(db, rpc("DoSomethingElse", {}), V1).json()
        assert body["error"]["code"] == -32601

    def test_a_message_without_an_id_or_parts_is_invalid_params(
        self, db: Session
    ) -> None:
        body = self.post(
            db, rpc("SendMessage", {"message": {"role": "ROLE_USER", "parts": []}}), V1
        ).json()
        assert body["error"]["code"] == -32602

    def test_a_result_never_carries_an_error(self, db: Session, experts: None) -> None:
        body = self.post(db, rpc("SendMessage", v1_message("hi")), V1).json()
        assert ("result" in body) != ("error" in body)

    def test_an_oversized_body_is_refused(self, db: Session) -> None:
        huge = {"padding": "x" * 100_000}
        response = self.post(db, huge, V1)
        assert response.status_code == 413


class TestWiring:
    def test_the_integrated_backend_does_not_host_it(self) -> None:
        """Chat and Chris reach the registry over A2A as a separate service."""
        from app.main import app

        assert TestClient(app).get(CARD_PATH).status_code == 404

    def test_it_runs_on_its_own_without_the_rest_of_the_backend(self) -> None:
        client = TestClient(create_standalone_app())
        assert client.get("/health").json()["status"] == "ok"
        assert client.get(CARD_PATH).status_code == 200

    def test_it_does_not_import_chris(self) -> None:
        import subprocess
        import sys

        code = (
            "import sys, app.registry.a2a_app;"
            "bad = [m for m in sys.modules if m.startswith('app.chris')];"
            "print(bad)"
        )
        out = subprocess.run(
            [sys.executable, "-c", code], capture_output=True, text=True, check=True
        ).stdout.strip()
        assert out == "[]"

    def test_on_cloud_run_a_missing_public_url_fails_closed(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("K_SERVICE", "openbeavs-registry-agent")
        monkeypatch.delenv("REGISTRY_PUBLIC_URL", raising=False)
        root = FastAPI()
        root.mount(MOUNT_PATH, create_registry_a2a_app())
        client = TestClient(root)
        assert client.get(CARD_PATH).status_code == 503
        assert client.post(RPC_PATH, json={}).status_code == 503

    def test_the_public_url_setting_is_used(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("K_SERVICE", "openbeavs-registry-agent")
        monkeypatch.setenv("REGISTRY_PUBLIC_URL", "https://registry.example.run.app/")
        root = FastAPI()
        root.mount(MOUNT_PATH, create_registry_a2a_app())
        card = TestClient(root).get(CARD_PATH).json()
        assert card["supportedInterfaces"][0]["url"] == (
            f"https://registry.example.run.app{MOUNT_PATH}/"
        )
