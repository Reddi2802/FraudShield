"""
Shared pytest fixtures.

Every test gets a fresh, isolated, in-memory SQLite database — never the
real `fraud_detection.db` file that the running app / seed_db.py use.
This means:
  - tests are fast (no disk I/O)
  - tests don't interfere with each other (fresh schema per test)
  - running the test suite is completely harmless to your seeded demo
    data — nothing here ever touches it.
"""

from __future__ import annotations

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from db.base import Base

# Importing db.models is required, not decorative — it executes every
# model class body, which registers all 14 tables on Base.metadata.
# Without this import, create_all() below would silently create zero
# tables. Same gotcha as api/main.py — see the comment there.
import db.models  # noqa: F401


@pytest.fixture()
def test_engine():
    """
    A fresh in-memory SQLite engine, one per test.

    StaticPool is required for in-memory SQLite specifically: without it,
    each new connection gets its own separate (and empty) in-memory
    database, which would make writes in one part of a test invisible to
    reads in another part of the same test.
    """
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(bind=engine)
    yield engine
    engine.dispose()


@pytest.fixture()
def db_session(test_engine):
    """A session bound to the fresh test engine, for agent-level unit tests."""
    TestSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=test_engine)
    session = TestSessionLocal()
    try:
        yield session
    finally:
        session.close()
