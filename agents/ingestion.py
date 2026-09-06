"""
Ingestion Agent.

Week 1 scope only: validate + enrich an incoming transaction with
customer/account/device/merchant context. Deliberately does NOT produce a
risk decision — Risk Synthesis (week 4) and the orchestrator (LangGraph,
week 4) don't exist yet, and this agent shouldn't guess at a shape those
components haven't defined. See ROADMAP.md / chat history: the API
response schema has no `decision` field until week 4, on purpose, so
adding it now doesn't force a schema migration later.

Identity handling mirrors scripts/seed_db.py's get-or-create pattern, but
operates on one transaction at a time (a live request) rather than a
batch loaded from CSV. If this logic starts to drift between the two
call sites, that's a signal to extract a shared helper — not urgent at
Week 1 scale.
"""

from __future__ import annotations

from datetime import datetime, timezone

from passlib.hash import bcrypt
from sqlalchemy.orm import Session

from agents.uid import compute_uid
from db.models import Account, Customer, Device, Merchant, Transaction

# Same rationale as seed_db.py: fabricated, not a real secret, exists only
# so a newly-created (never-before-seen) Customer has *something* in
# hashed_password, satisfying the non-nullable column, until real
# onboarding/auth flows exist.
_PLACEHOLDER_PASSWORD = "ChangeMe123!"


class IngestionError(ValueError):
    """Raised when an incoming transaction fails validation."""


def _get_or_create_customer(session: Session, uid: str, card6: str | None) -> Customer:
    customer = session.query(Customer).filter_by(synthetic_uid=uid).one_or_none()
    if customer is not None:
        return customer

    # New UID never seen before -> new synthetic customer + account.
    # customer_id isn't known yet, so email must be derived from the UID
    # itself (stable, unique) rather than a counter that requires an
    # existing row count query.
    customer = Customer(
        synthetic_uid=uid,
        name=f"Customer {uid}",
        email=f"{uid}@example.invalid",
        hashed_password=bcrypt.hash(_PLACEHOLDER_PASSWORD),
    )
    session.add(customer)
    session.flush()  # need customer.customer_id for the Account FK below

    account = Account(
        customer_id=customer.customer_id,
        account_number=f"ACCT-{uid}",
        account_type=card6 or "unknown",
    )
    session.add(account)
    session.flush()

    return customer


def _get_account(session: Session, customer: Customer) -> Account:
    # Week 1 simplification: one Account per Customer (see chat / ADR-011
    # discussion — IEEE-CIS gives no signal to split a customer into
    # multiple distinct accounts). Take the first/only account.
    account = (
        session.query(Account).filter_by(customer_id=customer.customer_id).first()
    )
    if account is None:
        raise IngestionError(
            f"Customer {customer.customer_id} (uid={customer.synthetic_uid}) "
            "has no associated Account — data integrity issue."
        )
    return account


def _get_or_create_merchant(session: Session, product_cd: str) -> Merchant:
    merchant = session.query(Merchant).filter_by(category=product_cd).one_or_none()
    if merchant is not None:
        return merchant

    merchant = Merchant(name=f"Merchant Category {product_cd}", category=product_cd)
    session.add(merchant)
    session.flush()
    return merchant


def _get_or_create_device(
    session: Session,
    customer: Customer,
    device_type: str | None,
    device_info: str | None,
) -> Device | None:
    # Strict, same as seed_db.py: no device row at all if no identity
    # signal was submitted with this transaction.
    if device_type is None and device_info is None:
        return None

    fingerprint = f"{customer.synthetic_uid}:{device_type}:{device_info}"
    device = session.query(Device).filter_by(device_fingerprint=fingerprint).one_or_none()
    if device is not None:
        device.last_seen_at = datetime.now(timezone.utc)
        return device

    device = Device(
        customer_id=customer.customer_id,
        device_fingerprint=fingerprint,
        device_type=device_type or "unknown",
    )
    session.add(device)
    session.flush()
    return device


def process_transaction(
    session: Session,
    *,
    card1: float,
    addr1: float | None,
    d1: float | None,
    card6: str | None,
    amount: float,
    currency: str,
    product_cd: str,
    device_type: str | None = None,
    device_info: str | None = None,
) -> Transaction:
    """
    Validate and enrich one incoming transaction, persisting it and any
    newly-required Customer/Account/Device/Merchant rows.

    Returns the created Transaction ORM object (caller/route is
    responsible for shaping the API response and committing/rolling back).
    """
    if amount <= 0:
        raise IngestionError("amount must be positive")
    if not currency or len(currency) != 3:
        raise IngestionError("currency must be a 3-letter code, e.g. 'USD'")
    if not product_cd:
        raise IngestionError("product_cd is required")

    uid = compute_uid(card1, addr1, d1)

    customer = _get_or_create_customer(session, uid, card6)
    account = _get_account(session, customer)
    merchant = _get_or_create_merchant(session, product_cd)
    device = _get_or_create_device(session, customer, device_type, device_info)

    transaction = Transaction(
        account_id=account.account_id,
        merchant_id=merchant.merchant_id,
        device_id=device.device_id if device is not None else None,
        amount=amount,
        currency=currency.upper(),
        submitted_at=datetime.now(timezone.utc),
    )
    session.add(transaction)
    session.flush()

    return transaction
