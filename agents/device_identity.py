"""
Shared device-identity logic — used by BOTH agents/ingestion.py (live,
one transaction at a time) and scripts/seed_db.py (batch, from CSV rows).

Extracted here because ingestion.py's original docstring flagged this
exact risk: "If this logic starts to drift between the two call sites,
that's a signal to extract a shared helper." The Week 2 schema change
(Device<->Customer many-to-many via DeviceCustomerLink, device-intrinsic
fingerprinting) made the logic complex enough that drift risk stopped
being hypothetical.

FINGERPRINT SCHEME — validated against real IEEE-CIS data (see chat):
  - If DeviceInfo is present, is NOT one of the generic OS-only buckets
    (see GENERIC_DEVICE_INFO below), and a browser string (id_31) is
    present: fingerprint is device-intrinsic (DeviceInfo + browser only,
    no customer identity in it). This is what enables cross-customer
    reuse detection — the actual point of the Week 2 schema change.
  - Otherwise (missing DeviceInfo, missing browser, or DeviceInfo is a
    generic bucket like "Windows"/"iOS Device"): falls back to a
    customer-scoped fingerprint (the original Week 1 scheme). This is a
    deliberate degrade, not a bug — real data showed generic buckets
    collapse thousands of distinct accounts into one fingerprint (median
    15 distinct UIDs, max 2030), which would manufacture false
    cross-customer "reuse" signal if used as-is. A device that can't be
    fingerprinted specifically enough is treated as unlinkable, not
    linked incorrectly.

GENERIC_DEVICE_INFO was derived from real train_identity.csv: these are
the top-frequency DeviceInfo values that are OS/engine names, not device
models. If you re-run the collision check against a different data slice
and find more/fewer generic values, update this set and re-document in
DECISIONS.md — it's a measured list, not a guess.
"""

from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy.orm import Session

from db.models import Customer, Device, DeviceCustomerLink

GENERIC_DEVICE_INFO = frozenset({
    "Windows",
    "iOS Device",
    "MacOS",
    "Trident/7.0",
    "rv:11.0",
    "rv:57.0",
    "rv:59.0",
})


def build_device_fingerprint(
    synthetic_uid: str,
    device_type: str | None,
    device_info: str | None,
    browser: str | None,
) -> tuple[str, bool]:
    """
    Returns (fingerprint, is_intrinsic).

    is_intrinsic=True means the fingerprint identifies the physical device
    independent of who's using it (cross-customer reuse detection works).
    is_intrinsic=False means it fell back to the customer-scoped scheme
    (reuse_count for this device will always be 1, by construction — that's
    expected, not a bug, for devices we can't fingerprint specifically).
    """
    if device_info and device_info not in GENERIC_DEVICE_INFO and browser:
        return f"{device_info}::{browser}", True

    # Fallback deliberately excludes browser: browser version changes
    # between a customer's own sessions (updates, different reported
    # builds) are common and NOT a "new device" — including it here
    # fragmented ~75% of generic-device customers into multiple Device
    # rows for what was really one device. Matches the original Week 1
    # fallback key exactly (uid:type:info), so reuse-across-sessions for
    # a single customer behaves the same as it always did.
    return f"{synthetic_uid}:{device_type}:{device_info}", False


def _aware(dt: datetime) -> datetime:
    """SQLite returns naive datetimes on reload; treat them as UTC."""
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def get_or_create_device_and_link(
    session: Session,
    customer: Customer,
    device_type: str | None,
    device_info: str | None,
    browser: str | None = None,
    seen_at: datetime | None = None,
) -> Device | None:
    """
    Strict, same as Week 1: no Device row at all if no identity signal was
    submitted with this transaction.

    seen_at: the transaction's own timestamp (submitted_at). Replay/seed
    callers MUST pass it — otherwise first_seen_at is stamped with the real
    wall clock (2026) while the transactions are dated 2017-2018, and Device
    Trust's device_age goes hugely negative. Defaults to now() only for
    genuinely live traffic.

    Always creates/reuses a DeviceCustomerLink row alongside the Device —
    this is what makes reuse_count queryable later, instead of needing a
    separate backfill step.
    """
    if device_type is None and device_info is None:
        return None

    fingerprint, _is_intrinsic = build_device_fingerprint(
        customer.synthetic_uid, device_type, device_info, browser
    )

    now = _aware(seen_at) if seen_at is not None else datetime.now(timezone.utc)

    device = session.query(Device).filter_by(device_fingerprint=fingerprint).one_or_none()
    if device is None:
        device = Device(
            device_fingerprint=fingerprint,
            device_type=device_type or "unknown",
            first_seen_at=now,
            last_seen_at=now,
        )
        session.add(device)
        session.flush()
    else:
        # min/max so out-of-order rows (batch seeding) can't move
        # first_seen_at forward or last_seen_at backward.
        device.first_seen_at = min(_aware(device.first_seen_at), now)
        device.last_seen_at = max(_aware(device.last_seen_at), now)

    link = (
        session.query(DeviceCustomerLink)
        .filter_by(device_id=device.device_id, customer_id=customer.customer_id)
        .one_or_none()
    )
    if link is None:
        link = DeviceCustomerLink(
            device_id=device.device_id,
            customer_id=customer.customer_id,
            first_seen_at=now,
            last_seen_at=now,
        )
        session.add(link)
        session.flush()
    else:
        link.first_seen_at = min(_aware(link.first_seen_at), now)
        link.last_seen_at = max(_aware(link.last_seen_at), now)

    return device
