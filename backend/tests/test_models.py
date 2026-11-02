"""Unit tests for the 5 core SQLAlchemy models.

Tests CRUD operations, relationships, cascade deletes, and the anonymous
iframe workflow with mid-chat authentication promotion.
"""

import time

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from app.db.base import Base
from app.models import Agent, Chat, Message, Ticket, User


@pytest.fixture
def db_session() -> Session:
    """Create an isolated in-memory SQLite database session for each test."""
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
    )
    Base.metadata.create_all(bind=engine)
    TestingSessionLocal = sessionmaker(
        autocommit=False, autoflush=False, bind=engine, expire_on_commit=False
    )
    session = TestingSessionLocal()
    try:
        yield session
    finally:
        session.close()
        Base.metadata.drop_all(bind=engine)


def test_create_agent(db_session: Session):
    """Test creating an A2A agent record."""
    agent = Agent(
        id="honors-college",
        name="Honors College Agent",
        description="Answers questions about OSU Honors College",
        endpoint_url="https://agents.oregonstate.edu/honors/message/send",
        card_url="https://agents.oregonstate.edu/honors/.well-known/agent.json",
        trust_tier="public",
        skills=["honors thesis", "scholarships", "advising"],
        capabilities={"streaming": True},
    )
    db_session.add(agent)
    db_session.commit()

    saved = db_session.get(Agent, "honors-college")
    assert saved is not None
    assert saved.name == "Honors College Agent"
    assert saved.trust_tier == "public"
    assert "honors thesis" in saved.skills
    assert saved.is_active is True


def test_create_user(db_session: Session):
    """Test creating an authenticated OSU user from SSO claims."""
    user = User(
        id="beaverb",
        email="beaverb@oregonstate.edu",
        display_name="Benny Beaver",
        role="student",
        kms_key_ref="gcp-kms://projects/openbeavs/cryptoKeys/beaverb",
    )
    db_session.add(user)
    db_session.commit()

    saved = db_session.get(User, "beaverb")
    assert saved is not None
    assert saved.email == "beaverb@oregonstate.edu"
    assert saved.role == "student"


def test_anonymous_iframe_chat_and_messages(db_session: Session):
    """Test creating an anonymized iframe session on an OSU domain with TTL."""
    now = int(time.time())
    ttl_expires = now + 7200  # 2 hours

    chat = Chat(
        user_id=None,  # Anonymized: no student account
        guest_session_id="guest_uuid_12345",
        title="Library Hours Query",
        source_domain="library.oregonstate.edu",
        session_type="guest",
        expires_at=ttl_expires,
    )
    db_session.add(chat)
    db_session.commit()

    msg1 = Message(
        chat_id=chat.id,
        sender_type="user",
        content="What time does the Valley Library close tonight?",
    )
    msg2 = Message(
        chat_id=chat.id,
        sender_type="agent",
        content="Valley Library is open until midnight tonight.",
        meta={"confidence": 0.95, "latency_ms": 140},
    )
    db_session.add_all([msg1, msg2])
    db_session.commit()

    saved_chat = db_session.get(Chat, chat.id)
    assert saved_chat is not None
    assert saved_chat.user_id is None
    assert saved_chat.guest_session_id == "guest_uuid_12345"
    assert saved_chat.source_domain == "library.oregonstate.edu"
    assert saved_chat.expires_at == ttl_expires
    assert len(saved_chat.messages) == 2
    assert saved_chat.messages[0].content.startswith("What time")


def test_guest_session_promotion_to_authenticated(db_session: Session):
    """Test promoting an anonymous iframe guest chat to an authenticated user."""
    # 1. User starts as anonymous guest in an iframe
    chat = Chat(
        user_id=None,
        guest_session_id="guest_promote_me",
        source_domain="engineering.oregonstate.edu",
        session_type="guest",
        expires_at=int(time.time()) + 3600,
    )
    db_session.add(chat)
    db_session.commit()

    msg = Message(
        chat_id=chat.id,
        sender_type="user",
        content="How do I declare my CS major?",
    )
    db_session.add(msg)
    db_session.commit()

    # 2. User signs in via OSU Microsoft SSO
    user = User(
        id="student123",
        email="student123@oregonstate.edu",
        display_name="Jane Doe",
        role="student",
    )
    db_session.add(user)
    db_session.commit()

    # 3. Promote session: attach user, clear guest id, remove expiration TTL
    chat.user_id = user.id
    chat.guest_session_id = None
    chat.session_type = "authenticated"
    chat.expires_at = None
    db_session.commit()

    # 4. Verify promotion
    updated_chat = db_session.get(Chat, chat.id)
    assert updated_chat.user_id == "student123"
    assert updated_chat.guest_session_id is None
    assert updated_chat.session_type == "authenticated"
    assert updated_chat.expires_at is None
    assert len(updated_chat.messages) == 1


def test_cascade_delete_on_chat_purge(db_session: Session):
    """Test that purging an expired chat cascades and deletes all its messages."""
    chat = Chat(
        user_id=None,
        guest_session_id="guest_delete_me",
        session_type="guest",
    )
    db_session.add(chat)
    db_session.commit()

    msg = Message(
        chat_id=chat.id,
        sender_type="user",
        content="Temporary message",
    )
    db_session.add(msg)
    db_session.commit()

    msg_id = msg.id

    # Delete parent chat (simulating TTL cleanup)
    db_session.delete(chat)
    db_session.commit()

    # Verify message was also deleted
    assert db_session.get(Message, msg_id) is None


def test_create_ticket(db_session: Session):
    """Test submitting a support/bug feedback ticket."""
    ticket = Ticket(
        name="Alex Smith",
        email="smitha@oregonstate.edu",
        issue_type="bug",
        description="The library agent did not return weekend hours properly.",
        info={"browser": "Firefox", "os": "Windows"},
    )
    db_session.add(ticket)
    db_session.commit()

    saved = db_session.get(Ticket, ticket.id)
    assert saved is not None
    assert saved.status == "new"
    assert saved.issue_type == "bug"
    assert saved.resolved_at is None
