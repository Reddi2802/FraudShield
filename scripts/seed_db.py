"""
Seed the SQLite DB from IEEE-CIS train_transaction.csv / train_identity.csv.

Decisions baked into this script (see docs/DECISIONS.md for the full
reasoning — this file just implements them):

- Identity (ADR-011, amended Week 3): Customer.synthetic_uid =
  agents.uid.compute_uid on (card1, addr1, D1n), where
  D1n = floor(TransactionDT/86400 - D1). This is a probabilistic proxy,
  not a verified key. Raw D1 is a tenure counter that drifts daily and
  fragmented single cards across UIDs — see agents/uid.py.
- Customer.billing_region (Week 2) persists the cleaned addr1 value —
  profile context only, NOT a rule-trigger field (see rule_compliance.py's
  docstring for why a billing-mismatch rule is structurally unreachable
  given addr1 is already part of the UID).
- Fabricated demo credentials: Customer.name / email / hashed_password
  have NO basis in IEEE-CIS (which has no such fields) — they exist only
  so the seeded Customer rows can demo-login once JWT auth is built
  (ADR-010). All seeded customers share one demo password; this is never
  meant to be a real credential.
- isFraud is intentionally NOT written anywhere in this DB. It's a
  training-time label consumed directly from the raw CSV by
  ml/train_isolation_forest.py in week 3 — this seed script populates the
  *operational* schema (what a live system would have), not the ML
  training set.
- Merchant identity doesn't exist in IEEE-CIS either. ProductCD (5 low-
  cardinality codes) is the closest proxy — one Merchant row is created
  per distinct ProductCD value, not per transaction.
- Device identity (Week 2): fingerprinting + DeviceCustomerLink creation
  is delegated to agents/device_identity.py, the SAME module
  agents/ingestion.py uses for live transactions — see that module's
  docstring for the fingerprint scheme (device-intrinsic when DeviceInfo
  is specific enough, customer-scoped fallback otherwise) and why it's
  shared rather than reimplemented here.
- TransactionDT is a timedelta, not a timestamp. A reference start date
  of 2017-12-01 is a commonly-cited community estimate for this dataset
  (not confirmed by Vesta) — used here only to produce plausible-looking
  submitted_at values, not treated as ground truth.

Run with:
    uv run python -m scripts.seed_db
"""

from __future__ import annotations

import random
from datetime import timedelta
from pathlib import Path

import pandas as pd
from passlib.hash import bcrypt

from agents.device_identity import get_or_create_device_and_link
from agents.uid import REFERENCE_START, clean_component, compute_uid
from db.models import Account, Customer, Merchant, Transaction
from db.session import SessionLocal, init_db

# ── Config ───────────────────────────────────────────────────────────────

DATA_DIR = Path("data/raw")
TRANSACTION_CSV = DATA_DIR / "train_transaction.csv"
IDENTITY_CSV = DATA_DIR / "train_identity.csv"

N_CUSTOMERS = 1500  # per project decision: medium volume
MIN_TRANSACTIONS_PER_UID = 8  # exclude thin-history UIDs from the demo DB —
# Behavioral Analysis (week 3) builds per-UID, time-gated history features
# and needs prior transactions to establish "normal" for that customer.
# Even with the D1n fix, most UIDs across the full dataset are still thin
# (57.4% are single-transaction), so uniform-random sampling over all UIDs
# mostly picks thin ones. This filter is a SEEDING/DEMO-DATA POLICY only —
# it does not change the UID definition (ADR-011) or how Behavioral
# Analysis trains from the raw CSV in week 3.
MAX_TRANSACTIONS_PER_UID = 150  # exclude implausibly high-count UIDs.
# IEEE-CIS spans ~6 months; a UID with hundreds/thousands of transactions
# is not a real, unusually active customer — it's almost certainly a
# CARD1+ADDR1+D1 COLLISION, where the masked value space merged several
# genuinely different people into one UID. Without this cap, high-count
# outliers are exactly the ones the >=8 floor is most likely to keep,
# which would seed a "customer" that's actually a blend of several real
# people. 150 is a generous but bounded ceiling (~1 txn/day sustained),
# not a rigorously derived number — check the printed top-10 counts below
# and adjust if the real distribution suggests otherwise.
RANDOM_SEED = 42
DEMO_PASSWORD = "ChangeMe123!"  # shared demo credential, not a real secret
COMMIT_BATCH_SIZE = 500

TRANSACTION_COLUMNS = [
    "TransactionID",
    "TransactionDT",
    "TransactionAmt",
    "ProductCD",
    "card1",
    "card6",
    "addr1",
    "D1",
]
# id_31 (browser string) added Week 2 — required, alongside DeviceInfo, for
# device-intrinsic fingerprinting (agents/device_identity.py). Without it
# every seeded device falls back to customer-scoped fingerprinting, which
# defeats the point of the schema migration.
IDENTITY_COLUMNS = ["TransactionID", "DeviceType", "DeviceInfo", "id_31"]


def _fabricate_name(index: int) -> str:
    """Deterministic placeholder name — not real, not inferred from data."""
    return f"Seed Customer {index:05d}"


def _fabricate_email(index: int) -> str:
    return f"seed.customer.{index:05d}@example.invalid"


def _account_number(index: int) -> str:
    return f"ACCT-{index:010d}"


def load_source_data() -> pd.DataFrame:
    if not TRANSACTION_CSV.exists() or not IDENTITY_CSV.exists():
        raise FileNotFoundError(
            f"Expected {TRANSACTION_CSV} and {IDENTITY_CSV} — download the "
            "IEEE-CIS dataset and place train_transaction.csv / "
            "train_identity.csv under data/raw/ before running this script."
        )

    print("Loading train_transaction.csv (this is the ~667MB file, may take a bit)...")
    transactions = pd.read_csv(TRANSACTION_CSV, usecols=TRANSACTION_COLUMNS)

    print("Loading train_identity.csv...")
    identity = pd.read_csv(IDENTITY_CSV, usecols=IDENTITY_COLUMNS)

    print("Joining on TransactionID (left join — most transactions have no identity row)...")
    merged = transactions.merge(identity, on="TransactionID", how="left")

    print("Computing synthetic UID (card1+addr1+D1n) per row...")
    merged["synthetic_uid"] = merged.apply(
        lambda row: compute_uid(row["card1"], row["addr1"], row["D1"], row["TransactionDT"] / 86400),
        axis=1,
    )

    return merged


def sample_customers(
    df: pd.DataFrame,
    n: int,
    seed: int,
    min_transactions: int,
    max_transactions: int,
) -> pd.DataFrame:
    uid_counts = df["synthetic_uid"].value_counts()
    print(f"Found {len(uid_counts):,} distinct synthetic UIDs in the loaded data.")
    print(f"  UID transaction-count distribution: min={uid_counts.min()}, "
          f"median={uid_counts.median():.1f}, max={uid_counts.max()}, "
          f"mean={uid_counts.mean():.2f}")
    print(f"  Top 10 highest-count UIDs (extreme outliers here are almost "
          f"certainly card1+addr1+D1 collisions, not real high-activity "
          f"customers): {uid_counts.head(10).to_dict()}")

    qualifying_uids = uid_counts[
        (uid_counts >= min_transactions) & (uid_counts <= max_transactions)
    ].index.tolist()
    print(
        f"{len(qualifying_uids):,} UIDs fall within [{min_transactions}, "
        f"{max_transactions}] transactions (the pool sampling draws from — "
        "excludes both thin-history UIDs and implausibly-high-count UIDs "
        "that are likely collisions, not real customers)."
    )

    if len(qualifying_uids) < n:
        print(
            f"WARNING: only {len(qualifying_uids)} UIDs meet the "
            f"[{min_transactions}, {max_transactions}] range, fewer than "
            f"the requested {n} — seeding all of them instead. Consider "
            "widening the range if you need more customers."
        )
        chosen = qualifying_uids
    else:
        rng = random.Random(seed)
        chosen = rng.sample(qualifying_uids, n)

    chosen_set = set(chosen)
    subset = df[df["synthetic_uid"].isin(chosen_set)].copy()
    subset.sort_values("TransactionDT", inplace=True)
    return subset


def seed(df: pd.DataFrame) -> None:
    init_db()
    session = SessionLocal()

    try:
        # ── Merchants: one per distinct ProductCD, created once up front ──
        merchant_by_code: dict[str, Merchant] = {}
        for code in sorted(df["ProductCD"].dropna().unique()):
            merchant = Merchant(name=f"Merchant Category {code}", category=str(code))
            session.add(merchant)
            merchant_by_code[code] = merchant
        session.flush()  # assigns merchant_id without committing yet
        print(f"Created {len(merchant_by_code)} merchant rows (one per ProductCD).")

        customer_by_uid: dict[str, Customer] = {}
        account_by_uid: dict[str, Account] = {}

        n_transactions = 0
        n_devices_before = 0
        customer_counter = 0

        for _, row in df.iterrows():
            uid = row["synthetic_uid"]

            # ── get-or-create Customer + Account for this UID ──
            customer = customer_by_uid.get(uid)
            if customer is None:
                customer_counter += 1
                customer = Customer(
                    synthetic_uid=uid,
                    billing_region=clean_component(row["addr1"]),
                    name=_fabricate_name(customer_counter),
                    email=_fabricate_email(customer_counter),
                    hashed_password=bcrypt.hash(DEMO_PASSWORD),
                )
                session.add(customer)
                session.flush()  # need customer.customer_id for the Account FK
                customer_by_uid[uid] = customer

                account_type = str(row["card6"]) if pd.notna(row["card6"]) else "unknown"
                account = Account(
                    customer_id=customer.customer_id,
                    account_number=_account_number(customer_counter),
                    account_type=account_type,
                )
                session.add(account)
                session.flush()
                account_by_uid[uid] = account

            account = account_by_uid[uid]

            # ── device: shared helper (agents/device_identity.py), same
            # logic path as live ingestion — strict creation, device-
            # intrinsic fingerprint when possible, customer-scoped
            # fallback otherwise, DeviceCustomerLink handled internally ──
            # submitted_at must be computed BEFORE the device call: Device /
            # DeviceCustomerLink first_seen_at / last_seen_at are stamped
            # from it (seen_at), not from the wall clock. Otherwise replayed
            # devices get 2026 timestamps against 2017-2018 transactions and
            # Device Trust's device_age goes hugely negative.
            submitted_at = REFERENCE_START + timedelta(seconds=int(row["TransactionDT"]))

            device_type = row.get("DeviceType")
            device_info = row.get("DeviceInfo")
            browser = row.get("id_31")
            device = get_or_create_device_and_link(
                session,
                customer,
                str(device_type) if pd.notna(device_type) else None,
                str(device_info) if pd.notna(device_info) else None,
                str(browser) if pd.notna(browser) else None,
                seen_at=submitted_at,
            )
            if device is not None:
                n_devices_before += 1  # counts device-bearing rows, not distinct devices (see summary query below)

            # ── Transaction ──
            merchant = merchant_by_code[row["ProductCD"]]
            transaction = Transaction(
                account_id=account.account_id,
                merchant_id=merchant.merchant_id,
                device_id=device.device_id if device is not None else None,
                amount=float(row["TransactionAmt"]),
                currency="USD",
                submitted_at=submitted_at,
            )
            session.add(transaction)
            n_transactions += 1

            if n_transactions % COMMIT_BATCH_SIZE == 0:
                session.commit()
                print(f"  ...committed {n_transactions:,} transactions so far")

        session.commit()

        from db.models import Device, DeviceCustomerLink  # local import: summary-only query

        from sqlalchemy import func

        n_distinct_devices = session.query(Device).count()
        n_shared_devices = (
            session.query(DeviceCustomerLink.device_id)
            .group_by(DeviceCustomerLink.device_id)
            .having(func.count(DeviceCustomerLink.customer_id.distinct()) > 1)
            .count()
        )

        print(
            f"\nDone. Seeded {len(customer_by_uid):,} customers, "
            f"{n_distinct_devices:,} distinct devices "
            f"({n_shared_devices:,} linked to more than one customer), "
            f"{n_transactions:,} transactions, {len(merchant_by_code)} merchants."
        )

    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


def main() -> None:
    df = load_source_data()
    subset = sample_customers(
        df, N_CUSTOMERS, RANDOM_SEED, MIN_TRANSACTIONS_PER_UID, MAX_TRANSACTIONS_PER_UID
    )
    print(f"Seeding from {len(subset):,} transaction rows across the sampled UIDs...")
    seed(subset)


if __name__ == "__main__":
    main()
