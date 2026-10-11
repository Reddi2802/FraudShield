"""
Declarative base shared by every ORM model.

UTCDateTime: SQLite has no timezone-aware datetime type, so SQLAlchemy
hands back NAIVE datetimes on any row reloaded from the database, while
agents build timezone-aware UTC values in Python (ingestion's submitted_at,
seed_db's REFERENCE_START + TransactionDT). Mixing the two raises
"can't compare/subtract offset-naive and offset-aware datetimes" — and it
only happens when an object has been evicted from the session's identity
map, so it passes in a short test and crashes in the live pipeline.

Fixing it here, once, at the type level means every datetime column in
every model (and every future agent) always sees aware-UTC values.
Bound values are normalized to UTC; naive values are assumed to be UTC.
"""

from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import DateTime
from sqlalchemy.orm import DeclarativeBase
from sqlalchemy.types import TypeDecorator


class UTCDateTime(TypeDecorator):
    impl = DateTime
    cache_ok = True

    def process_bind_param(self, value, dialect):
        if value is None:
            return None
        if value.tzinfo is not None:
            value = value.astimezone(timezone.utc).replace(tzinfo=None)
        return value

    def process_result_value(self, value, dialect):
        if value is None:
            return None
        if value.tzinfo is None:
            return value.replace(tzinfo=timezone.utc)
        return value.astimezone(timezone.utc)


class Base(DeclarativeBase):
    # Every Mapped[datetime] column in db/models.py uses UTCDateTime.
    type_annotation_map = {datetime: UTCDateTime}
