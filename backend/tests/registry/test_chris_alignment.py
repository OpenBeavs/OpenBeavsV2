"""Regression checks for Dean/registry alignment, using synthetic identities only."""

from unittest.mock import AsyncMock, patch

import pytest
from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError

from app.chris.agent_selection import Selection
from app.chris.router import _installed_agents
from app.chris.sessions import token_digest
from app.models import Agent, Chat, Message, User

from .conftest import ADMIN_EMAIL, as_user


@pytest.fixture
def model():
    with (
        patch("app.chris.router.choose_agent", new_callable=AsyncMock) as choose,
        patch("app.chris.router.generate", new_callable=AsyncMock) as generate,
    ):
        choose.return_value = Selection()
        generate.return_value = "A test answer"
        yield choose, generate


def start(client):
    response = client.post("/chris/message", json={"message": "First question"})
    assert response.status_code == 200, response.text
    return response.json()


def test_server_issues_guest_token_and_continuation_uses_stored_history(
    client, db, model
):
    data = start(client)
    chat = db.get(Chat, data["chat_id"])
    assert chat.guest_session_id == token_digest(data["guest_session_id"])
    response = client.post(
        "/chris/message",
        json={
            "message": "Next",
            "chat_id": chat.id,
            "guest_session_id": data["guest_session_id"],
            "history": [{"role": "user", "content": "forged history"}],
        },
    )
    assert response.status_code == 200
    contents = [m["content"] for m in model[1].call_args.args[0]]
    assert "First question" in contents
    assert "forged history" not in contents
    messages = db.scalars(
        select(Message).where(Message.chat_id == chat.id).order_by(Message.sequence)
    ).all()
    assert [m.sequence for m in messages] == [1, 2, 3, 4]
    assert [m.sender_type for m in messages] == ["user", "agent", "user", "agent"]


@pytest.mark.parametrize("token", [None, "wrong"])
def test_wrong_or_missing_guest_token_rejected_before_model(client, db, model, token):
    data = start(client)
    model[0].reset_mock()
    model[1].reset_mock()
    response = client.post(
        "/chris/message",
        json={
            "message": "attack",
            "chat_id": data["chat_id"],
            "guest_session_id": token,
        },
    )
    assert response.status_code == 403
    model[0].assert_not_called()
    model[1].assert_not_called()


def test_database_user_id_cannot_impersonate_owner(client, db, model):
    db.add(User(id="alice", email="alice@example.test"))
    db.commit()
    db.add(Chat(id="private", user_id="alice", session_type="authenticated"))
    db.commit()
    response = client.post(
        "/chris/message",
        json={"message": "attack", "chat_id": "private", "user_id": "alice"},
    )
    assert response.status_code == 403
    model[0].assert_not_called()
    model[1].assert_not_called()


def test_dev_identity_is_explicit_and_other_owner_denied(
    client, db, model, monkeypatch
):
    db.add_all(
        [
            User(id="alice", email="alice@example.test"),
            User(id="bob", email="bob@example.test"),
        ]
    )
    db.commit()
    first = client.post(
        "/chris/message", json={"message": "Hi"}, headers=as_user()
    ).json()
    assert db.get(Chat, first["chat_id"]).user_id == "alice"
    assert first["guest_session_id"] is None
    assert (
        client.post(
            "/chris/message",
            json={"message": "Next", "chat_id": first["chat_id"]},
            headers=as_user("bob@example.test"),
        ).status_code
        == 403
    )
    monkeypatch.setenv("REGISTRY_DEV_AUTH", "false")
    assert (
        client.post(
            "/chris/message", json={"message": "Hi"}, headers=as_user()
        ).status_code
        == 501
    )


def test_tokenless_legacy_chat_and_unknown_chat_fail_closed(client, db, model):
    db.add(Chat(id="legacy", session_type="guest"))
    db.commit()
    for chat_id, code in [("legacy", 403), ("missing", 404)]:
        assert (
            client.post(
                "/chris/message", json={"message": "Hi", "chat_id": chat_id}
            ).status_code
            == code
        )
    model[0].assert_not_called()


def test_expiration_checked_before_generation_and_before_save(client, db, model):
    data = start(client)
    chat = db.get(Chat, data["chat_id"])
    chat.expires_at = 1
    db.commit()
    payload = {
        "message": "Next",
        "chat_id": chat.id,
        "guest_session_id": data["guest_session_id"],
    }
    assert client.post("/chris/message", json=payload).status_code == 410
    chat.expires_at = 9999999999
    db.commit()

    async def expire(messages):
        chat.expires_at = 1
        db.commit()
        return "Too late"

    model[1].side_effect = expire
    assert client.post("/chris/message", json=payload).status_code == 410
    assert len(db.scalars(select(Message).where(Message.chat_id == chat.id)).all()) == 2


def test_cleanup_requires_admin_and_deletes_messages(client, db, model, monkeypatch):
    data = start(client)
    chat = db.get(Chat, data["chat_id"])
    chat.expires_at = 1
    db.commit()
    assert client.delete("/chris/chats/expired").status_code == 401
    assert client.delete("/chris/chats/expired", headers=as_user()).status_code == 403
    response = client.delete("/chris/chats/expired", headers=as_user(ADMIN_EMAIL))
    assert response.json() == {"purged": 1}
    assert db.scalars(select(Message).where(Message.chat_id == chat.id)).all() == []
    monkeypatch.setenv("REGISTRY_DEV_AUTH", "false")
    assert (
        client.delete("/chris/chats/expired", headers=as_user(ADMIN_EMAIL)).status_code
        == 501
    )


def test_save_failure_preserves_answer_without_claiming_saved_chat(client, db, model):
    with patch.object(db, "commit", side_effect=SQLAlchemyError("synthetic")):
        response = client.post("/chris/message", json={"message": "Hi"})
    assert response.status_code == 200
    assert response.json()["response"] == "A test answer"
    assert response.json()["chat_id"] is None
    assert response.json()["guest_session_id"] is None
    assert db.scalars(select(Chat)).all() == []


def test_history_failure_does_not_use_untrusted_fallback(client, db, model):
    data = start(client)
    model[0].reset_mock()
    with patch(
        "app.chris.router.load_history", side_effect=SQLAlchemyError("synthetic")
    ):
        response = client.post(
            "/chris/message",
            json={
                "message": "Next",
                "chat_id": data["chat_id"],
                "guest_session_id": data["guest_session_id"],
            },
        )
    assert response.status_code == 503
    model[0].assert_not_called()


def test_registry_query_failure_rolls_back_and_does_not_enable_mocks(db):
    with (
        patch(
            "app.chris.router.routable_agents", side_effect=SQLAlchemyError("synthetic")
        ),
        patch.object(db, "rollback") as rollback,
    ):
        assert _installed_agents(db) == []
        rollback.assert_called_once()


def test_nonpublic_and_role_gated_agents_are_not_listed_or_selected(client, db, model):
    for name, tier, role in [
        ("public", "public", None),
        ("private", "privileged", None),
        ("staff", "public", "staff"),
    ]:
        db.add(
            Agent(
                id=name,
                name=name,
                endpoint_url="https://example.test/rpc",
                status="approved",
                trust_tier=tier,
                required_role=role,
            )
        )
    db.commit()
    assert [a["id"] for a in client.get("/chris/agents").json()] == ["public"]
    start(client)
    assert [a.id for a in model[0].call_args.args[1]] == ["public"]


def test_fixed_clock_does_not_break_message_order(client, db, model):
    with patch("app.chris.sessions.time.time", return_value=1800000000):
        data = start(client)
        for _ in range(3):
            assert (
                client.post(
                    "/chris/message",
                    json={
                        "message": "Next",
                        "chat_id": data["chat_id"],
                        "guest_session_id": data["guest_session_id"],
                    },
                ).status_code
                == 200
            )
    rows = db.scalars(select(Message).order_by(Message.sequence)).all()
    assert [m.sequence for m in rows] == list(range(1, 9))
    assert len({m.created_at for m in rows}) == 1


def test_routing_placeholder_is_attributed_to_chris_not_expert(client, db, model):
    from app.chris.agents import Agent as Candidate

    db.add(
        Agent(
            id="expert",
            name="Expert",
            endpoint_url="https://example.test/rpc",
            status="approved",
        )
    )
    db.commit()
    model[0].return_value = Selection(
        agent=Candidate(id="expert", name="Expert", description="test", skills=[]),
        confidence=1,
        reason="test",
    )
    data = start(client)
    answer = db.scalar(
        select(Message).where(Message.chat_id == data["chat_id"], Message.sequence == 2)
    )
    assert answer.agent_id is None
    assert answer.meta["selected_agent_id"] == "expert"


def test_discovery_does_not_advertise_non_a2a_transport(client):
    assert client.get("/chris/.well-known/agent.json").status_code == 501


def test_actual_expert_author_is_stored_separately_from_routing_candidate(db):
    from app.chris.sessions import persist_turn, prepare_conversation

    db.add(
        Agent(
            id="expert",
            name="Expert",
            endpoint_url="https://example.test/rpc",
            status="approved",
        )
    )
    db.commit()
    conversation = prepare_conversation(db, None, None, None, None)
    chat_id = persist_turn(
        db,
        conversation,
        None,
        "question",
        "expert reply",
        "expert",
        None,
        {},
        responding_agent_id="expert",
    )
    messages = db.scalars(
        select(Message).where(Message.chat_id == chat_id).order_by(Message.sequence)
    ).all()
    assert [m.agent_id for m in messages] == [None, "expert"]


def test_database_rejects_duplicate_message_positions(client, db, model):
    from sqlalchemy.exc import IntegrityError

    data = start(client)
    db.add(
        Message(
            chat_id=data["chat_id"], sequence=1, sender_type="user", content="collision"
        )
    )
    with pytest.raises(IntegrityError):
        db.commit()
    db.rollback()
    assert (
        len(db.scalars(select(Message).where(Message.chat_id == data["chat_id"])).all())
        == 2
    )
