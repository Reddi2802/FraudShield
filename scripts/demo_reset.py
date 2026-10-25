"""
Rebuild the demo database from scratch so every recording / rehearsal starts identical.

    uv run python -m scripts.demo_reset --yes

Why it exists: every transaction you submit while testing is permanent, and earlier submissions change a
customer's history (and so what later transactions are compared with). A clean, reproducible start state is
what makes a demo repeatable.

Steps (each is the project's own script, run in order; the first failure stops the reset):
  1. delete fraud_detection.db            (asks for --yes: this DESTROYS all demo data)
  2. scripts.seed_db                       customers, accounts, devices, transactions from the IEEE-CIS CSVs
                                           (slow: loads the 667 MB CSV and hashes 1,500 demo passwords, several minutes)
  3. scripts.seed_investigators            the two demo investigators
  4. ml.train_behavioral --register-only   registers the already-trained model in ml/artifacts/ (no retraining)
  5. scripts.run_network_batch             shared-device graph and NetworkRiskScore rows
  6. scripts.check_seed                    sanity check; must report 0 bad devices

Needs data/raw/train_transaction.csv and train_identity.csv, and a trained artifact in ml/artifacts/
(run `uv run python -m ml.train_behavioral` once if there is none). Nothing is retrained here.
"""

from __future__ import annotations

import argparse
import subprocess
import sys
import time
from pathlib import Path

DB_FILE = Path("fraud_detection.db")
ARTIFACT_DIR = Path("ml/artifacts")
RAW = [Path("data/raw/train_transaction.csv"), Path("data/raw/train_identity.csv")]

STEPS = [
    ("Seeding customers, devices and transactions", ["-m", "scripts.seed_db"]),
    ("Seeding demo investigators", ["-m", "scripts.seed_investigators"]),
    ("Registering the trained behavioral model", ["-m", "ml.train_behavioral", "--register-only"]),
    ("Running the Network Intelligence batch", ["-m", "scripts.run_network_batch"]),
    ("Checking the seed", ["-m", "scripts.check_seed"]),
]


def preflight() -> list[str]:
    problems = [f"missing {p}" for p in RAW if not p.exists()]
    if not list(ARTIFACT_DIR.glob("*.meta.json")):
        problems.append("no trained model in ml/artifacts/ (run: uv run python -m ml.train_behavioral)")
    return problems


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--yes", action="store_true", help="confirm that fraud_detection.db will be deleted")
    args = parser.parse_args()

    problems = preflight()
    if problems:
        print("Cannot reset yet:\n  - " + "\n  - ".join(problems))
        return 1
    if not args.yes:
        print("This DELETES fraud_detection.db and rebuilds it. Stop the API server first, then re-run with --yes.")
        return 1

    if DB_FILE.exists():
        try:
            DB_FILE.unlink()
        except PermissionError:
            print("Cannot delete fraud_detection.db: stop the API server (uvicorn) and close any DB viewer, then retry.")
            return 1
        print(f"Deleted {DB_FILE}")

    started = time.time()
    for number, (label, argv) in enumerate(STEPS, start=1):
        print(f"\n[{number}/{len(STEPS)}] {label} ...", flush=True)
        step_started = time.time()
        result = subprocess.run([sys.executable, *argv])
        if result.returncode != 0:
            print(f"\nStep failed: {label} (exit {result.returncode}). Reset stopped; the database is incomplete.")
            return result.returncode
        print(f"    done in {time.time() - step_started:.0f}s")

    print(f"\nDemo database ready in {time.time() - started:.0f}s. Start it with: uv run uvicorn api.main:app")
    print("Demo logins (password ChangeMe123!): seed.customer.00001@example.invalid (customer), "
          "investigator1@example.invalid (investigator).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
