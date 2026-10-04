"""
Ingestion Agent.

Week 1 scope only: validate + enrich an incoming transaction with
customer/account/device/merchant context. Deliberately does NOT produce a
risk decision — Risk Synthesis (week 4) and the orchestrator (LangGraph,
week 4) don't exist yet. See ROADMAP.md / DECISIONS.md.

Week 2 update: Customer.billing_region is now persisted at customer
creation (raw addr1, cleaned the same way as the UID computation — see
agents/uid.py's clean_component). NOTE: this is stored as customer
profile context, NOT as input to a "billing mismatch" rule — addr1 is
part of the synthetic_uid itself, so a transaction with a different addr1
resolves to a different customer entirely; a same-customer mismatch is
structurally unreachable. See DECISIONS.md for the full reasoning.

Device identity (fingerprinting + DeviceCustomerLink) is delegated to
agents/device_identity.py, shared with scripts/seed_db.py, so the two
call sites can't drift apart (see that module's docstring).

Week 3 update (ADR-011 amendment): compute_uid now needs days_since_epoch,
because the UID's D1 component was normalized (D1n) to fix a fragmentation
bug — see agents/uid.py's module docstring for the full reasoning and the
real-data numbers behind it. This agent accepts an optional
`transaction_dt` (seconds, same units as IEEE-CIS's TransactionDT) so a
demo/replay client can simulate historical timing and get a UID consistent
with the seeded data. Without it, a real live transaction still works, but
its D1n — and therefore its UID — is anchored to the actual current date,
not the dataset's ~6-month window, so it will NOT match any seeded
customer even if the same card1/addr1/D1 were reused. That's an accepted,
documented limitation of using a calendar-anchored identity component for
genuinely live (non-replay) traffic, not a bug — IEEE-CIS's D1 has no real
production equivalent outside this dataset in the first place.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from passlib.hash import bcrypt
from sqlalchemy.orm import Session

from agents.device_identity import get_or_create_device_and_link
from agents.uid import clean_component, compute_uid, days_since_epoch
from db.models import Account, Customer, Device, Merchant, Transaction
from agents.uid import REFERENCE_START

# Same rationale as seed_db.py: fabricated, not a real secret, exists only
# so a newly-created (never-before-seen) Customer has *something* in
# hashed_password, satisfying the non-nullable column, until real
# onboarding/auth flows exist.
_PLACEHOLDER_PASSWORD = "ChangeMe123!"


class IngestionError(ValueError):
    """Raised when an incoming transaction fails validation."""


def _get_or_create_customer(
    session: Session, uid: str, card6: str | None, addr1: float | None
) -> Customer:
    customer = session.query(Customer).filter_by(synthetic_uid=uid).one_or_none()
    if customer is not None:
        return customer

    # New UID never seen before -> new synthetic customer + account.
    # customer_id isn't known yet, so email must be derived from the UID
    # itself (stable, unique) rather than a counter that requires an
    # existing row count query.
    customer = Customer(
        synthetic_uid=uid,
        billing_region=clean_component(addr1),
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
    browser: str | None = None,
    transaction_dt: float | None = None,
) -> Transaction:
    """
    Validate and enrich one incoming transaction, persisting it and any
    newly-required Customer/Account/Device/DeviceCustomerLink/Merchant rows.

    transaction_dt: optional simulated TransactionDT (seconds, IEEE-CIS
    units). When provided, both the UID's D1n component AND submitted_at
    are derived from it, so a CSV-replay demo gets real, consistent
    inter-transaction time gaps (not everything collapsing to ~now()).
    When omitted, falls back to real current time for both — see this
    module's docstring for what that means for UID matching.

    Returns the created Transaction ORM object (caller/route is
    responsible for shaping the API response and committing/rolling back).
    """
    if amount <= 0:
        raise IngestionError("amount must be positive")
    if not currency or len(currency) != 3:
        raise IngestionError("currency must be a 3-letter code, e.g. 'USD'")
    if not product_cd:
        raise IngestionError("product_cd is required")

    if transaction_dt is not None:
        submitted_at = REFERENCE_START + timedelta(seconds=transaction_dt)
        dse = transaction_dt / 86400
    else:
        submitted_at = datetime.now(timezone.utc)
        dse = days_since_epoch(submitted_at)

    uid = compute_uid(card1, addr1, d1, dse)

    customer = _get_or_create_customer(session, uid, card6, addr1)
    account = _get_account(session, customer)
    merchant = _get_or_create_merchant(session, product_cd)
    device = get_or_create_device_and_link(session, customer, device_type, device_info, browser)

    transaction = Transaction(
        account_id=account.account_id,
        merchant_id=merchant.merchant_id,
        device_id=device.device_id if device is not None else None,
        amount=amount,
        currency=currency.upper(),
        submitted_at=submitted_at,
    )
    session.add(transaction)
    session.flush()

    return transaction
