"""
Sanity-check the seeded fraud_detection.db after running scripts/seed_db.py.

Run from the repo root:
    uv run python -m scripts.check_seed

What "healthy" looks like:
  - customers == N_CUSTOMERS you seeded (1,500 unless the pool was smaller)
  - txns/customer min >= 8 (the ADR-013 floor) and max <= 150
  - submitted_at range falls in the dataset window (Dec 2017 - mid 2018),
    NOT in 2026
  - "devices first-seen AFTER their first transaction" == 0. A non-zero
    count means device timestamps are coming from the wall clock instead
    of the transaction time (the Week 3 seen_at bug).
"""

from __future__ import annotations

from sqlalchemy import func, select

from db.models import Account, Customer, Device, DeviceCustomerLink, Transaction
from db.session import SessionLocal


def main() -> None:
    with SessionLocal() as s:
        count = lambda col: s.scalar(select(func.count(col)))  # noqa: E731

        n_customers = count(Customer.customer_id)
        n_devices = count(Device.device_id)
        n_links = count(DeviceCustomerLink.device_customer_link_id)
        n_txns = count(Transaction.transaction_id)
        print(f"customers={n_customers:,} | devices={n_devices:,} | "
              f"links={n_links:,} | transactions={n_txns:,}")

        with_device = s.scalar(
            select(func.count(Transaction.transaction_id)).where(
                Transaction.device_id.is_not(None)
            )
        )
        print(f"transactions carrying a device: {with_device:,} "
              f"({with_device / max(n_txns, 1):.1%})")

        shared = s.scalar(
            select(func.count()).select_from(
                select(DeviceCustomerLink.device_id)
                .group_by(DeviceCustomerLink.device_id)
                .having(func.count(DeviceCustomerLink.customer_id.distinct()) > 1)
                .subquery()
            )
        )
        print(f"devices linked to more than one customer: {shared:,}")

        per_customer = (
            select(func.count(Transaction.transaction_id))
            .join(Account, Transaction.account_id == Account.account_id)
            .group_by(Account.customer_id)
        )
        counts = sorted(c for (c,) in s.execute(per_customer))
        if counts:
            print(f"txns/customer min / median / max: "
                  f"{counts[0]} / {counts[len(counts) // 2]} / {counts[-1]}")

        lo = s.scalar(select(func.min(Transaction.submitted_at)))
        hi = s.scalar(select(func.max(Transaction.submitted_at)))
        print(f"submitted_at range: {lo} -> {hi}")

        first_tx = (
            select(
                Transaction.device_id,
                func.min(Transaction.submitted_at).label("t0"),
            )
            .where(Transaction.device_id.is_not(None))
            .group_by(Transaction.device_id)
            .subquery()
        )
        bad = s.scalar(
            select(func.count())
            .select_from(Device)
            .join(first_tx, first_tx.c.device_id == Device.device_id)
            .where(Device.first_seen_at > first_tx.c.t0)
        )
        status = "OK" if bad == 0 else "BUG: device timestamps are not from transaction time"
        print(f"devices first-seen AFTER their first transaction (must be 0): {bad:,}  [{status}]")


if __name__ == "__main__":
    main()
