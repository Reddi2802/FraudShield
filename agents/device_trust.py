"""
Device Trust Agent — Week 2

Rule-based / statistical device scoring (ADR-002: no ML — no device
ground-truth label to train or validate against).

Restored to the originally-planned three signals now that the schema
supports them (DeviceCustomerLink many-to-many, device-intrinsic
fingerprinting — see agents/device_identity.py):

  - reuse_count              : distinct customers ever linked to this
                                device, via DeviceCustomerLink. For a
                                device that fell back to customer-scoped
                                fingerprinting (generic DeviceInfo, or
                                missing browser signal), this will always
                                be 1 — that's correct, not a bug: we
                                couldn't fingerprint it specifically
                                enough to ever link a second customer to
                                it in the first place.
  - is_first_seen_globally   : true iff no OTHER transaction (any
                                customer) used this device before this one.
  - is_new_device_for_customer: true iff no PRIOR transaction by THIS
                                customer used this device before this one.
                                Computed from transaction history, not
                                from DeviceCustomerLink.first_seen_at,
                                to stay consistent with how
                                rule_compliance.py already computes
                                history (pure query over Transaction rows,
                                not reliant on mutable timestamp fields
                                that could be touched out of order in a
                                batch/backfill run).
  - device_age                : real timedelta, Device.first_seen_at is a
                                genuine timestamp (global first-seen, any
                                customer).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import timedelta
from typing import Optional

from sqlalchemy.orm import Session

from db.models import Account, DeviceCustomerLink, Transaction


@dataclass
class DeviceTrustResult:
    transaction_id: int
    device_id: Optional[int]
    reuse_count: int
    is_first_seen_globally: bool
    is_new_device_for_customer: bool
    device_age: Optional[timedelta]

    @property
    def no_device(self) -> bool:
        return self.device_id is None


def run_device_trust(session: Session, transaction: Transaction) -> DeviceTrustResult:
    if transaction.device_id is None:
        return DeviceTrustResult(
            transaction_id=transaction.transaction_id,
            device_id=None,
            reuse_count=0,
            is_first_seen_globally=False,
            is_new_device_for_customer=False,
            device_age=None,
        )

    device = transaction.device  # relationship, already loaded via FK

    reuse_count = (
        session.query(DeviceCustomerLink.customer_id)
        .filter(DeviceCustomerLink.device_id == transaction.device_id)
        .distinct()
        .count()
    )

    prior_any_customer = (
        session.query(Transaction)
        .filter(
            Transaction.device_id == transaction.device_id,
            Transaction.transaction_id != transaction.transaction_id,
            Transaction.submitted_at < transaction.submitted_at,
        )
        .count()
    )
    is_first_seen_globally = prior_any_customer == 0

    customer_id = transaction.account.customer_id
    prior_this_customer = (
        session.query(Transaction)
        .join(Account, Transaction.account_id == Account.account_id)
        .filter(
            Transaction.device_id == transaction.device_id,
            Account.customer_id == customer_id,
            Transaction.transaction_id != transaction.transaction_id,
            Transaction.submitted_at < transaction.submitted_at,
        )
        .count()
    )
    is_new_device_for_customer = prior_this_customer == 0

    return DeviceTrustResult(
        transaction_id=transaction.transaction_id,
        device_id=transaction.device_id,
        reuse_count=reuse_count,
        is_first_seen_globally=is_first_seen_globally,
        is_new_device_for_customer=is_new_device_for_customer,
        device_age=transaction.submitted_at - device.first_seen_at,
    )


# NOTE: still writes nothing to the DB — signal producer for Risk Synthesis
# (Week 4). AgentLog is available for a raw-output audit trail if you want
# it, same option flagged as before — not added here, wasn't in ROADMAP.md's
# Week 2 checklist item for this agent.
