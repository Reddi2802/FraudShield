"""
Device Trust Agent — Week 2

Rule-based / statistical device scoring (ADR-002: no ML — no device
ground-truth label to train or validate against).

SCHEMA-FORCED SCOPE REDUCTION — read before extending this file:
ingestion.py's device_fingerprint is built as
    f"{customer.synthetic_uid}:{device_type}:{device_info}"
which means the UID is baked into the fingerprint itself, and Device.customer_id
is a single FK (not a many-to-many join). Two different customers on the same
physical device produce two different Device rows — there is no way, under
the current schema, to observe "this device is shared across customers."

Practical consequence: the three signals originally planned —
(1) cross-customer reuse_count, (2) is_first_seen_globally,
(3) is_new_device_for_customer — collapse into two, because (1) is
unobservable and (2)/(3) become identical (a device can only ever belong to
one customer, so "first seen globally" == "new for this customer" always).

This file implements what the schema actually supports:
  - device_transaction_count : how many PRIOR transactions this specific
                                customer has made on this specific device.
                                A tenure/familiarity signal, not a fraud-ring
                                signal — rename expectations accordingly.
  - is_first_use_of_device   : true iff device_transaction_count == 0.
  - device_age               : REAL timedelta (Device.first_seen_at is a
                                genuine timestamp, not a dataset-relative
                                proxy — no longer needs the "_proxy" naming
                                from the earlier draft).

If cross-customer reuse detection matters for your Network Intelligence
story (Week 5), that requires a schema change now: either strip the UID out
of the fingerprint (fingerprint should be a property of the DEVICE, not the
device+customer pair) and add a proper Device<->Customer association table,
or accept that Network Intelligence computes its own device/address graph
independently of this table and treat Device Trust as customer-scoped only.
That's your call to make and document — not implemented here.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import timedelta
from typing import Optional

from sqlalchemy.orm import Session

from db.models import Transaction


@dataclass
class DeviceTrustResult:
    transaction_id: int
    device_id: Optional[int]
    device_transaction_count: int          # prior txns on this device, this customer only
    is_first_use_of_device: bool
    device_age: Optional[timedelta]        # None if no device on this transaction

    @property
    def no_device(self) -> bool:
        return self.device_id is None


def run_device_trust(session: Session, transaction: Transaction) -> DeviceTrustResult:
    if transaction.device_id is None:
        return DeviceTrustResult(
            transaction_id=transaction.transaction_id,
            device_id=None,
            device_transaction_count=0,
            is_first_use_of_device=False,
            device_age=None,
        )

    device = transaction.device  # relationship, already loaded via FK

    prior_count = (
        session.query(Transaction)
        .filter(
            Transaction.device_id == transaction.device_id,
            Transaction.transaction_id != transaction.transaction_id,
            Transaction.submitted_at < transaction.submitted_at,
        )
        .count()
    )

    return DeviceTrustResult(
        transaction_id=transaction.transaction_id,
        device_id=transaction.device_id,
        device_transaction_count=prior_count,
        is_first_use_of_device=(prior_count == 0),
        device_age=transaction.submitted_at - device.first_seen_at,
    )


# NOTE: This agent currently writes nothing to the DB — it's a signal
# producer for Risk Synthesis (Week 4), same design as before. AgentLog
# exists in your schema specifically for "independent audit trail of every
# agent's raw output" (per models.py's own docstring) and would be a
# natural place to persist DeviceTrustResult per transaction — not added
# here since it wasn't in ROADMAP.md's Week 2 checklist item for this
# agent. Flagging as a real option, not a silent omission.
