"""
Tests for agents/ingestion.py.

Per ROADMAP.md's week-1 checklist: "valid input, malformed input,
transaction with no device." Also covers UID reuse (the actual mechanism
the whole identity-resolution approach, ADR-011, depends on working) and
strict device creation (ADR-011/chat: only create a Device when identity
data actually exists, don't fabricate one).
"""

from __future__ import annotations

import pytest

from agents.ingestion import IngestionError, process_transaction
from db.models import Customer, Device


VALID_KWARGS = dict(
    card1=13926.0,
    addr1=315.0,
    d1=2.0,
    # Fixed transaction_dt makes the resulting UID deterministic across
    # test runs (D1n = floor(864000/86400 - 2) = 8). Without this, a test
    # relying on real now() would compute a different D1n every day.
    transaction_dt=864000.0,
    card6="credit",
    amount=125.50,
    currency="USD",
    product_cd="W",
)


def test_valid_transaction_creates_customer_account_and_transaction(db_session):
    transaction = process_transaction(db_session, **VALID_KWARGS)
    db_session.commit()

    assert transaction.transaction_id is not None
    assert transaction.amount == 125.50
    assert transaction.currency == "USD"

    customer = db_session.query(Customer).filter_by(synthetic_uid="13926-315-8").one()
    assert transaction.account.customer_id == customer.customer_id


def test_same_uid_reuses_existing_customer_and_account(db_session):
    first = process_transaction(db_session, **VALID_KWARGS)
    db_session.commit()

    second = process_transaction(db_session, **VALID_KWARGS)
    db_session.commit()

    assert first.account_id == second.account_id
    assert first.transaction_id != second.transaction_id

    customer_count = db_session.query(Customer).count()
    assert customer_count == 1, "same UID must not create a second Customer"


def test_different_uid_creates_a_new_customer(db_session):
    process_transaction(db_session, **VALID_KWARGS)
    db_session.commit()

    other_kwargs = dict(VALID_KWARGS, card1=99999.0)
    process_transaction(db_session, **other_kwargs)
    db_session.commit()

    assert db_session.query(Customer).count() == 2


def test_no_device_info_leaves_device_id_null(db_session):
    kwargs = dict(VALID_KWARGS, device_type=None, device_info=None)
    transaction = process_transaction(db_session, **kwargs)
    db_session.commit()

    assert transaction.device_id is None
    assert db_session.query(Device).count() == 0, (
        "strict device creation: no identity data means no fabricated Device row"
    )


def test_device_info_creates_a_device_and_reuses_it_on_repeat(db_session):
    kwargs = dict(VALID_KWARGS, device_type="mobile", device_info="iOS Device")

    first = process_transaction(db_session, **kwargs)
    db_session.commit()
    second = process_transaction(db_session, **kwargs)
    db_session.commit()

    assert first.device_id is not None
    assert first.device_id == second.device_id, "same customer + same device info should reuse the Device row"
    assert db_session.query(Device).count() == 1


def test_negative_amount_is_rejected(db_session):
    kwargs = dict(VALID_KWARGS, amount=-5.0)
    with pytest.raises(IngestionError, match="amount"):
        process_transaction(db_session, **kwargs)


def test_zero_amount_is_rejected(db_session):
    kwargs = dict(VALID_KWARGS, amount=0)
    with pytest.raises(IngestionError, match="amount"):
        process_transaction(db_session, **kwargs)


def test_invalid_currency_length_is_rejected(db_session):
    kwargs = dict(VALID_KWARGS, currency="US")
    with pytest.raises(IngestionError, match="currency"):
        process_transaction(db_session, **kwargs)


def test_missing_product_cd_is_rejected(db_session):
    kwargs = dict(VALID_KWARGS, product_cd="")
    with pytest.raises(IngestionError, match="product_cd"):
        process_transaction(db_session, **kwargs)
