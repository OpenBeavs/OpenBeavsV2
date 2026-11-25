"""Tests for authenticated chat persistence, ownership isolation, and chat CRUD."""

from unittest.mock import AsyncMock, patch

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session, sessionmaker

from application_services.chat.a2a_client import ChrisReply, ChrisUnavailable
from application_services.chat.schemas import RoutedAgent, RoutingInfo
from application_services.database.base import ChatSystemBase
from application_services.database.session import get_db
from application_services.main import app
from application_services.models import Chat, Message, User
from tests.databases import chat_system_engine


@pytest.fixture(autouse=True)
def enable_dev_auth(monkeypatch: pytest.MonkeyPatch) -> None:
    """Enable local dev login for authenticated persistence tests."""
    monkeypatch.setenv("AUTH_BYPASS_DEV", "true")
    for marker in ("K_SERVICE", "K_REVISION", "K_CONFIGURATION"):
        monkeypatch.delenv(marker, raising=False)


@pytest.fixture
def test_db() -> Session:
    """Create an isolated chat-system database session for each test."""
    engine = chat_system_engine()
    TestingSessionLocal = sessionmaker(
        autocommit=False, autoflush=False, bind=engine, expire_on_commit=False
    )
    session = TestingSessionLocal()

    def override_get_db():
        try:
            yield session
        finally:
            pass

    app.dependency_overrides[get_db] = override_get_db
    yield session
    app.dependency_overrides.clear()
    session.close()
    ChatSystemBase.metadata.drop_all(bind=engine)


def _auth_headers(client: TestClient, email: str) -> dict[str, str]:
    response = client.post("/auth/dev/login", json={"email": email})
    assert response.status_code == 200
    token = response.json()["access_token"]
    return {"Authorization": f"Bearer {token}"}


@patch("application_services.chat.service.send_message", new_callable=AsyncMock)
def test_authenticated_new_chat_persists_turns_and_routing(
    mock_send: AsyncMock, test_db: Session
) -> None:
    """A signed-in user's turn creates a chat, saves both turns, and keeps expert attribution."""
    routing = RoutingInfo(
        status="selected",
        agent=RoutedAgent(
            id="math-expert",
            name="Math Expert",
            description="Arithmetic and algebra.",
        ),
    )
    mock_send.return_value = ChrisReply(text="The answer is 42.", routing=routing)

    client = TestClient(app)
    headers = _auth_headers(client, "alice@oregonstate.edu")
    response = client.post(
        "/chat/message",
        json={
            "message": "  What   is   6 times 7?  ",
            "source_domain": "math.oregonstate.edu",
        },
        headers=headers,
    )
    assert response.status_code == 200
    data = response.json()
    chat_id = data["chat_id"]
    assert isinstance(chat_id, str) and chat_id
    assert data["routed_to"] == "math-expert"
    assert data["agent_name"] == "Math Expert"

    chat = test_db.get(Chat, chat_id)
    assert chat is not None
    assert chat.user_id == "alice"
    assert chat.session_type == "authenticated"
    assert chat.expires_at is None
    assert chat.is_pinned is False
    assert chat.agent_id == "math-expert"
    assert chat.title == "What is 6 times 7?"
    assert chat.source_domain == "math.oregonstate.edu"

    messages = (
        test_db.query(Message)
        .filter(Message.chat_id == chat_id)
        .order_by(Message.created_at.asc())
        .all()
    )
    assert len(messages) == 2
    assert messages[0].sender_type == "user"
    assert messages[0].content == "What   is   6 times 7?"
    assert messages[1].sender_type == "agent"
    assert messages[1].content == "The answer is 42."
    assert messages[1].created_at > messages[0].created_at
    assert messages[1].meta["routing"]["agent"]["id"] == "math-expert"


@patch("application_services.chat.service.send_message", new_callable=AsyncMock)
def test_authenticated_followup_uses_db_history_and_ignores_client_history(
    mock_send: AsyncMock, test_db: Session
) -> None:
    """Continuing a saved chat replays stored DB turns to Chris instead of client history."""
    mock_send.side_effect = [
        ChrisReply(text="First answer."),
        ChrisReply(text="Second answer."),
    ]
    client = TestClient(app)
    headers = _auth_headers(client, "alice@oregonstate.edu")

    first = client.post(
        "/chat/message", json={"message": "First question"}, headers=headers
    )
    chat_id = first.json()["chat_id"]

    second = client.post(
        "/chat/message",
        json={
            "message": "Follow up",
            "chat_id": chat_id,
            "history": [{"role": "user", "content": "Tampered history"}],
        },
        headers=headers,
    )
    assert second.status_code == 200
    assert second.json()["chat_id"] == chat_id

    assert mock_send.await_args_list[1].args == (
        "Follow up",
        [
            {"role": "user", "content": "First question"},
            {"role": "assistant", "content": "First answer."},
        ],
    )

    detail = client.get(f"/chat/chats/{chat_id}", headers=headers)
    assert detail.status_code == 200
    msgs = detail.json()["messages"]
    assert [(m["role"], m["content"]) for m in msgs] == [
        ("user", "First question"),
        ("assistant", "First answer."),
        ("user", "Follow up"),
        ("assistant", "Second answer."),
    ]
    assert [m["created_at"] for m in msgs] == sorted(m["created_at"] for m in msgs)
    assert len({m["created_at"] for m in msgs}) == 4


@patch("application_services.chat.service.send_message", new_callable=AsyncMock)
def test_authenticated_failed_turn_does_not_persist(
    mock_send: AsyncMock, test_db: Session
) -> None:
    """Chris failures never create empty chats or partial messages for signed-in users."""
    client = TestClient(app)
    headers = _auth_headers(client, "alice@oregonstate.edu")

    mock_send.side_effect = ChrisUnavailable("down")
    failed = client.post("/chat/message", json={"message": "Hello"}, headers=headers)
    assert failed.status_code == 503
    assert test_db.query(Chat).count() == 0
    assert test_db.query(Message).count() == 0

    mock_send.side_effect = None
    mock_send.return_value = ChrisReply("Saved reply.")
    ok = client.post("/chat/message", json={"message": "Saved prompt"}, headers=headers)
    chat_id = ok.json()["chat_id"]

    mock_send.side_effect = ChrisUnavailable("down again")
    failed_followup = client.post(
        "/chat/message",
        json={"message": "Unsaved followup", "chat_id": chat_id},
        headers=headers,
    )
    assert failed_followup.status_code == 503
    assert test_db.query(Message).filter(Message.chat_id == chat_id).count() == 2


@patch("application_services.chat.service.send_message", new_callable=AsyncMock)
def test_authenticated_db_commit_failure_rolls_back(
    mock_send: AsyncMock, test_db: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A commit error rolls back cleanly and returns 503 without leaking DB details."""
    mock_send.return_value = ChrisReply("Answer.")
    client = TestClient(app)
    headers = _auth_headers(client, "alice@oregonstate.edu")

    def broken_commit():
        raise OperationalError("commit", {}, Exception("SECRET-SQL-DETAIL"))

    monkeypatch.setattr(test_db, "commit", broken_commit)
    response = client.post("/chat/message", json={"message": "Hello"}, headers=headers)
    assert response.status_code == 503
    assert "SECRET-SQL-DETAIL" not in response.text
    assert test_db.query(Chat).count() == 0
    assert test_db.query(Message).count() == 0


def test_unauthenticated_cannot_access_chat_crud_routes(test_db: Session) -> None:
    """Saved chat endpoints fail closed with 401 when unauthenticated."""
    client = TestClient(app)
    assert client.get("/chat/chats").status_code == 401
    assert client.get("/chat/chats/some-id").status_code == 401
    assert (
        client.patch("/chat/chats/some-id", json={"title": "Renamed"}).status_code == 401
    )
    assert client.delete("/chat/chats/some-id").status_code == 401


@patch("application_services.chat.service.send_message", new_callable=AsyncMock)
def test_idor_cross_user_chat_access_and_continuation_are_rejected(
    mock_send: AsyncMock, test_db: Session
) -> None:
    """A signed-in user cannot read, continue, modify, or delete another user's chat."""
    mock_send.return_value = ChrisReply("Alice's private reply.")
    client = TestClient(app)
    alice_headers = _auth_headers(client, "alice@oregonstate.edu")
    bob_headers = _auth_headers(client, "bob@oregonstate.edu")

    created = client.post(
        "/chat/message", json={"message": "Alice secret"}, headers=alice_headers
    )
    alice_chat_id = created.json()["chat_id"]
    mock_send.reset_mock()

    # Bob cannot continue, read, rename/pin, or delete Alice's chat.
    assert (
        client.post(
            "/chat/message",
            json={"message": "Injected", "chat_id": alice_chat_id},
            headers=bob_headers,
        ).status_code
        == 404
    )
    mock_send.assert_not_awaited()
    assert client.get(f"/chat/chats/{alice_chat_id}", headers=bob_headers).status_code == 404
    assert (
        client.patch(
            f"/chat/chats/{alice_chat_id}",
            json={"title": "Hijacked"},
            headers=bob_headers,
        ).status_code
        == 404
    )
    assert client.delete(f"/chat/chats/{alice_chat_id}", headers=bob_headers).status_code == 404

    # Alice's chat and turns remain untouched.
    alice_detail = client.get(f"/chat/chats/{alice_chat_id}", headers=alice_headers)
    assert alice_detail.status_code == 200
    assert alice_detail.json()["title"] == "Alice secret"
    assert len(alice_detail.json()["messages"]) == 2


@patch("application_services.chat.service.send_message", new_callable=AsyncMock)
def test_authenticated_user_cannot_adopt_legacy_guest_chat(
    mock_send: AsyncMock, test_db: Session
) -> None:
    """Legacy guest chats are never exposed or adoptable via authenticated chat routes."""
    test_db.add(User(id="alice", email="alice@oregonstate.edu", role="student"))
    test_db.flush()
    test_db.add(
        Chat(
            id="legacy-guest",
            user_id=None,
            guest_session_id="guest-tok",
            session_type="guest",
            title="Legacy guest",
        )
    )
    test_db.flush()
    test_db.add(
        Message(chat_id="legacy-guest", sender_type="user", content="Legacy guest text")
    )
    test_db.commit()

    client = TestClient(app)
    headers = _auth_headers(client, "alice@oregonstate.edu")
    assert client.get("/chat/chats/legacy-guest", headers=headers).status_code == 404
    assert (
        client.post(
            "/chat/message",
            json={"message": "Follow up", "chat_id": "legacy-guest"},
            headers=headers,
        ).status_code
        == 404
    )
    mock_send.assert_not_awaited()


@patch("application_services.chat.service.send_message", new_callable=AsyncMock)
def test_chat_list_detail_patch_and_delete_lifecycle(
    mock_send: AsyncMock, test_db: Session
) -> None:
    """Users can list, load with routing badges, rename, pin, and cascade-delete chats."""
    routing = RoutingInfo(
        status="selected",
        agent=RoutedAgent(id="osu-rag", name="OSU RAG", description="OSU knowledge"),
    )
    mock_send.side_effect = [
        ChrisReply(text="Answer 1.", routing=routing),
        ChrisReply(text="Answer 2."),
        ChrisReply(text="Bob answer."),
    ]
    client = TestClient(app)
    alice_headers = _auth_headers(client, "alice@oregonstate.edu")
    bob_headers = _auth_headers(client, "bob@oregonstate.edu")

    chat1 = client.post(
        "/chat/message", json={"message": "First chat"}, headers=alice_headers
    ).json()["chat_id"]
    chat2 = client.post(
        "/chat/message", json={"message": "Second chat"}, headers=alice_headers
    ).json()["chat_id"]
    client.post("/chat/message", json={"message": "Bob chat"}, headers=bob_headers)

    # Make chat2 newer so default ordering puts chat2 first before pinning chat1.
    test_db.get(Chat, chat1).updated_at = 100
    test_db.get(Chat, chat2).updated_at = 200
    test_db.commit()

    listed = client.get("/chat/chats", headers=alice_headers)
    assert listed.status_code == 200
    assert [c["id"] for c in listed.json()] == [chat2, chat1]

    # Pin and rename chat1.
    patched = client.patch(
        f"/chat/chats/{chat1}",
        json={"title": "  Renamed   First  ", "is_pinned": True},
        headers=alice_headers,
    )
    assert patched.status_code == 200
    assert patched.json()["title"] == "Renamed First"
    assert patched.json()["is_pinned"] is True

    # Pinned chat1 now precedes chat2.
    listed_after = client.get("/chat/chats", headers=alice_headers)
    assert [c["id"] for c in listed_after.json()] == [chat1, chat2]

    # Routing metadata survives reload via GET /chat/chats/{id}.
    detail = client.get(f"/chat/chats/{chat1}", headers=alice_headers)
    assert detail.status_code == 200
    assistant_msg = detail.json()["messages"][1]
    assert assistant_msg["routed_to"] == "osu-rag"
    assert assistant_msg["agent_name"] == "OSU RAG"
    assert assistant_msg["routing"]["agent"]["id"] == "osu-rag"

    # Validation checks on PATCH.
    assert client.patch(f"/chat/chats/{chat1}", json={}, headers=alice_headers).status_code == 400
    assert (
        client.patch(
            f"/chat/chats/{chat1}", json={"title": "   "}, headers=alice_headers
        ).status_code
        == 422
    )
    assert (
        client.patch(
            f"/chat/chats/{chat1}", json={"user_id": "bob"}, headers=alice_headers
        ).status_code
        == 422
    )

    # Delete cascades to messages while leaving other chats intact.
    deleted = client.delete(f"/chat/chats/{chat1}", headers=alice_headers)
    assert deleted.status_code == 204
    assert client.get(f"/chat/chats/{chat1}", headers=alice_headers).status_code == 404
    assert test_db.query(Message).filter(Message.chat_id == chat1).count() == 0
    assert test_db.query(Chat).count() == 2


def test_logout_clears_session_cookies(test_db: Session) -> None:
    """POST /auth/logout deletes openbeavs_token and ends the cookie session."""
    client = TestClient(app)
    login_resp = client.post(
        "/auth/dev/login", json={"email": "alice@oregonstate.edu"}
    )
    token = login_resp.json()["access_token"]
    client.cookies.set("openbeavs_token", token, domain="testserver.local")
    assert client.get("/auth/me").status_code == 200

    logout_resp = client.post("/auth/logout")
    assert logout_resp.status_code == 200
    assert logout_resp.json() == {"status": "ok"}
    set_cookies = logout_resp.headers.get_list("set-cookie")
    assert any(
        header.startswith("openbeavs_token=") and "Max-Age=0" in header and "Path=/" in header
        for header in set_cookies
    )
    assert client.get("/auth/me").status_code == 401
