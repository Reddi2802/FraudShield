"""
Seed two demo investigators (ADR-021). Idempotent: existing emails are skipped,
so it can be run any time without re-seeding the database.

    uv run python -m scripts.seed_investigators

Both share the demo password below — fabricated, not a real credential, the
same convention as the seeded customers (scripts/seed_db.py).
"""

from __future__ import annotations

from passlib.hash import bcrypt
from sqlalchemy.orm import Session

from db.models import Investigator
from db.session import SessionLocal, init_db

DEMO_PASSWORD = "ChangeMe123!"
DEMO_INVESTIGATORS = [
    ("Demo Investigator 1", "investigator1@example.invalid"),
    ("Demo Investigator 2", "investigator2@example.invalid"),
]


def seed_investigators(session: Session) -> tuple[int, int]:
    """Create the demo investigators that are missing. Flushes, never commits.
    Returns (created, skipped)."""
    created = skipped = 0
    for name, email in DEMO_INVESTIGATORS:
        if session.query(Investigator).filter(Investigator.email == email).first() is not None:
            skipped += 1
            continue
        session.add(
            Investigator(name=name, email=email, hashed_password=bcrypt.hash(DEMO_PASSWORD))
        )
        created += 1
    session.flush()
    return created, skipped


def main() -> None:
    init_db()
    with SessionLocal() as session:
        created, skipped = seed_investigators(session)
        session.commit()
    print(f"Investigators: {created} created, {skipped} already present.")


if __name__ == "__main__":
    main()
