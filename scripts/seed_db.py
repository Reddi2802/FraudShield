"""
Seed the SQLite DB from IEEE-CIS train_transaction.csv / train_identity.csv.

Decisions baked into this script (see docs/DECISIONS.md for the full
reasoning — this file just implements them):

- Identity (ADR-011): Customer.synthetic_uid = agents.uid.compute_uid on
  (card1, addr1, D1). This is a probabilistic proxy, not a verified key.
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
- Device rows are created STRICTLY: only when the source row has a match
  in train_identity.csv with a non-null DeviceType or DeviceInfo. Most
  transactions will have no device — this mirrors the real dataset
  (identity data covers a minority of transactions) rather than papering
  over it with fabricated devices.
- TransactionDT is a timedelta, not a timestamp. A reference start date
  of 2017-12-01 is a commonly-cited community estimate for this dataset
  (not confirmed by Vesta) — used here only to produce plausible-looking
  submitted_at values, not treated as ground truth.

Run with:
    uv run python -m scripts.seed_db
"""

from __future__ import annotations

import random
from datetime import datetime, timedelta
from pathlib import Path

import pandas as pd
from passlib.hash import bcrypt

from agents.uid import compute_uid
from db.models import Account, Customer, Device, Merchant, Transaction
from db.session import SessionLocal, init_db

# ── Config ───────────────────────────────────────────────────────────────

DATA_DIR = Path("data/raw")
TRANSACTION_CSV = DATA_DIR / "train_transaction.csv"
IDENTITY_CSV = DATA_DIR / "train_identity.csv"

N_CUSTOMERS = 1500  # per project decision: medium volume
RANDOM_SEED = 42
DEMO_PASSWORD = "ChangeMe123!"  # shared demo credential, not a real secret
REFERENCE_START = datetime(2017, 12, 1)  # community-estimated TransactionDT epoch
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
IDENTITY_COLUMNS = ["TransactionID", "DeviceType", "DeviceInfo"]


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

    print("Computing synthetic UID (card1+addr1+D1) per row...")
    merged["synthetic_uid"] = merged.apply(
        lambda row: compute_uid(row["card1"], row["addr1"], row["D1"]), axis=1
    )

    return merged


def sample_customers(df: pd.DataFrame, n: int, seed: int) -> pd.DataFrame:
    distinct_uids = df["synthetic_uid"].unique().tolist()
    print(f"Found {len(distinct_uids):,} distinct synthetic UIDs in the loaded data.")

    if len(distinct_uids) < n:
        print(
            f"WARNING: only {len(distinct_uids)} distinct UIDs available, "
            f"fewer than the requested {n} — seeding all of them instead."
        )
        chosen = distinct_uids
    else:
        rng = random.Random(seed)
        chosen = rng.sample(distinct_uids, n)

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
        device_by_key: dict[tuple[str, str, str], Device] = {}  # (uid, type, info) -> Device

        n_transactions = 0
        n_devices = 0
        customer_counter = 0

        for _, row in df.iterrows():
            uid = row["synthetic_uid"]

            # ── get-or-create Customer + Account for this UID ──
            customer = customer_by_uid.get(uid)
            if customer is None:
                customer_counter += 1
                customer = Customer(
                    synthetic_uid=uid,
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

            # ── strict Device creation: only if identity data exists ──
            device_type = row.get("DeviceType")
            device_info = row.get("DeviceInfo")
            device = None
            has_identity = pd.notna(device_type) or pd.notna(device_info)
            if has_identity:
                device_key = (uid, str(device_type), str(device_info))
                device = device_by_key.get(device_key)
                if device is None:
                    fingerprint = f"{uid}:{device_type}:{device_info}"
                    device = Device(
                        customer_id=customer.customer_id,
                        device_fingerprint=fingerprint,
                        device_type=str(device_type) if pd.notna(device_type) else "unknown",
                    )
                    session.add(device)
                    session.flush()
                    device_by_key[device_key] = device
                    n_devices += 1

            # ── Transaction ──
            merchant = merchant_by_code[row["ProductCD"]]
            submitted_at = REFERENCE_START + timedelta(seconds=int(row["TransactionDT"]))
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
        print(
            f"\nDone. Seeded {len(customer_by_uid):,} customers, "
            f"{n_devices:,} devices, {n_transactions:,} transactions, "
            f"{len(merchant_by_code)} merchants."
        )

    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


def main() -> None:
    df = load_source_data()
    subset = sample_customers(df, N_CUSTOMERS, RANDOM_SEED)
    print(f"Seeding from {len(subset):,} transaction rows across the sampled UIDs...")
    seed(subset)


if __name__ == "__main__":
    main()
