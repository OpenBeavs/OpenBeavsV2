"""Database engine, session factory, and FastAPI dependency.

Supports both local SQLite development and PostgreSQL (Google Cloud SQL)
in production, controlled via the DATABASE_URL environment variable.
"""

from collections.abc import Generator
from typing import Any

from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from app.config import get_database_url


def create_db_engine():
    """Create and configure the SQLAlchemy engine."""
    db_url = get_database_url()
    connect_args: dict[str, Any] = {}

    # SQLite needs check_same_thread=False for FastAPI concurrency
    if db_url.startswith("sqlite"):
        connect_args["check_same_thread"] = False

    return create_engine(
        db_url,
        connect_args=connect_args,
        pool_pre_ping=True,
    )


engine = create_db_engine()

SessionLocal = sessionmaker(
    autocommit=False,
    autoflush=False,
    bind=engine,
    expire_on_commit=False,
)


def get_db() -> Generator[Session, None, None]:
    """Yield a database session and safely close it after request completion.

    Usage in FastAPI route:
        @router.get("/example")
        def route(db: Session = Depends(get_db)):
            ...
    """
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
