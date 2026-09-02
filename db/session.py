"""
Engine + session setup. Nothing agent-specific lives here — agents/ and
api/ import `get_session` and never touch the engine directly, so swapping
SQLite for Postgres later (if you ever needed to) means editing this one
file, not every agent.
"""

from collections.abc import Generator

from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from db.base import Base

# SQLite file lives outside version control (see .gitignore) — swap this
# for an env var (DATABASE_URL) once there's a reason to (e.g. deploying).
DATABASE_URL = "sqlite:///./fraud_detection.db"

# check_same_thread=False is required for SQLite specifically when the
# same connection may be touched from FastAPI's async request handling
# and APScheduler's background thread (Network Intelligence's batch job).
engine = create_engine(DATABASE_URL, connect_args={"check_same_thread": False})

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


def init_db() -> None:
    """Create all tables. Call once at app startup (or from scripts/seed_db.py)."""
    Base.metadata.create_all(bind=engine)


def get_session() -> Generator[Session, None, None]:
    """FastAPI dependency: `session: Session = Depends(get_session)`."""
    session = SessionLocal()
    try:
        yield session
    finally:
        session.close()
