"""Exercise message migration with legacy data and repeatable initialization."""

from pathlib import Path

from alembic.config import Config
from sqlalchemy import create_engine, inspect, text

from alembic import command
from app.models import Message

BACKEND = Path(__file__).resolve().parents[2]


def config(url, monkeypatch):
    monkeypatch.setenv("DATABASE_URL", url)
    cfg = Config(str(BACKEND / "alembic.ini"))
    cfg.set_main_option("script_location", str(BACKEND / "alembic"))
    return cfg


def test_legacy_messages_keep_content_links_and_seconds(tmp_path, monkeypatch):
    url = f"sqlite:///{(tmp_path / 'legacy.db').as_posix()}"
    cfg = config(url, monkeypatch)
    command.upgrade(cfg, "a7c3e91d5b02")
    engine = create_engine(url)
    with engine.begin() as conn:
        conn.execute(
            text(
                "INSERT INTO chats (id,session_type,created_at,updated_at) VALUES ('chat','guest',100,100)"
            )
        )
        conn.execute(
            text(
                "INSERT INTO messages(id,chat_id,sender_type,content,created_at) VALUES ('b','chat','agent','answer',100),('a','chat','user','question',100)"
            )
        )
    command.upgrade(cfg, "head")
    with engine.connect() as conn:
        rows = conn.execute(
            text(
                "SELECT id,chat_id,content,sequence,agent_id,created_at FROM messages ORDER BY sequence"
            )
        ).all()
        assert rows == [
            ("a", "chat", "question", 1, None, 100),
            ("b", "chat", "answer", 2, None, 100),
        ]
    columns = {c["name"] for c in inspect(engine).get_columns("messages")}
    assert columns == set(Message.__table__.columns.keys())
    command.downgrade(cfg, "a7c3e91d5b02")
    with engine.connect() as conn:
        assert conn.execute(text("SELECT count(*) FROM messages")).scalar() == 2
    engine.dispose()


def test_init_db_uses_alembic_and_can_repeat(tmp_path, monkeypatch):
    url = f"sqlite:///{(tmp_path / 'init.db').as_posix()}"
    config(url, monkeypatch)
    from app.db.init_db import init_tables

    init_tables()
    init_tables()
    engine = create_engine(url)
    with engine.connect() as conn:
        assert (
            conn.execute(text("SELECT version_num FROM alembic_version")).scalar()
            == "b82f6d1a390c"
        )
    engine.dispose()


def test_postgres_message_migration_sql(monkeypatch, capsys):
    cfg = config("postgresql://user:placeholder@localhost/disposable", monkeypatch)
    command.upgrade(cfg, "a7c3e91d5b02:b82f6d1a390c", sql=True)
    sql = capsys.readouterr().out
    assert "ROW_NUMBER() OVER" in sql
    assert "UNIQUE (chat_id, sequence)" in sql
    assert "FOREIGN KEY(agent_id) REFERENCES agents (id) ON DELETE SET NULL" in sql


def test_mixed_timestamp_units_are_normalized_without_reordering(tmp_path, monkeypatch):
    url = f"sqlite:///{(tmp_path / 'mixed.db').as_posix()}"
    cfg = config(url, monkeypatch)
    command.upgrade(cfg, "a7c3e91d5b02")
    engine = create_engine(url)
    with engine.begin() as conn:
        conn.execute(
            text(
                "INSERT INTO chats (id,session_type,created_at,updated_at) VALUES ('chat','guest',1800000000,1800000000)"
            )
        )
        conn.execute(
            text(
                "INSERT INTO messages(id,chat_id,sender_type,content,created_at) VALUES ('ms','chat','agent','earlier',1800000000123),('sec','chat','user','later',1800000001)"
            )
        )
    command.upgrade(cfg, "head")
    with engine.connect() as conn:
        assert conn.execute(
            text("SELECT id,sequence,created_at FROM messages ORDER BY sequence")
        ).all() == [("ms", 1, 1800000000), ("sec", 2, 1800000001)]
    engine.dispose()
