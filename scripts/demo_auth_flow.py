"""
End-to-end demo of the auth flow against a RUNNING server (ADR-021).

    uv run uvicorn api.main:app            # terminal 1
    uv run python -m scripts.demo_auth_flow   # terminal 2

Logs in as the first seeded customer, submits three ordinary transactions and
then a large one for the SAME customer (so the amount rule fires), shows the
decisions and explanations, then logs in as an investigator, reviews the new
case and records feedback. Needs a seeded database and the demo investigators
(`uv run python -m scripts.seed_investigators`). Writes to the real database.
"""

from __future__ import annotations

import os
import re
import statistics
import sys
from datetime import datetime

import httpx

from agents.uid import REFERENCE_START
from db.models import Customer
from db.session import SessionLocal

BASE_URL = os.environ.get("API_URL", "http://127.0.0.1:8000")
PASSWORD = "ChangeMe123!"  # the shared demo password (seed_db.py, seed_investigators.py)
_UID = re.compile(r"^(\d+)-(NA|\d+)-(NA|-?\d+)$")


def parse_uid(uid: str) -> tuple[float, float | None, float | None]:
    """synthetic_uid 'card1-addr1-D1n' -> (card1, addr1 or None, D1n or None)."""
    match = _UID.match(uid)
    if match is None:
        raise ValueError(f"Unexpected synthetic_uid format: {uid}")
    card1, addr1, d1n = match.groups()
    return float(card1), None if addr1 == "NA" else float(addr1), None if d1n == "NA" else float(d1n)


def login(client: httpx.Client, email: str, role: str) -> dict:
    r = client.post("/auth/login", json={"email": email, "password": PASSWORD, "role": role})
    if r.status_code != 200:
        sys.exit(f"Login failed for {email} ({role}): {r.status_code} {r.text}")
    return {"Authorization": f"Bearer {r.json()['access_token']}"}


def main() -> None:
    with SessionLocal() as session:
        customer = (
            session.query(Customer)
            .filter(Customer.email.like("seed.customer.%"))
            .order_by(Customer.customer_id)
            .first()
        )
    if customer is None:
        sys.exit("No seeded customer found: run `uv run python -m scripts.seed_db` first.")
    card1, addr1, d1n = parse_uid(customer.synthetic_uid)

    with httpx.Client(base_url=BASE_URL, timeout=30) as client:
        headers = login(client, customer.email, "customer")
        history = client.get("/transactions/me", headers=headers).json()
        latest = max(datetime.fromisoformat(t["submitted_at"]) for t in history)
        base_dt = (latest - REFERENCE_START).total_seconds()
        typical = statistics.median(t["amount"] for t in history)
        spike = max(10 * statistics.mean(t["amount"] for t in history), 500.0)
        print(f"Customer {customer.customer_id} ({customer.email}), uid {customer.synthetic_uid}, "
              f"{len(history)} earlier transactions, typical amount {typical:.2f}\n")

        last = None
        for i, amount in enumerate([typical, typical, typical, spike], start=1):
            dt = base_dt + i * 3600
            payload = dict(
                # D1n = floor(days - D1)  =>  D1 = days - D1n keeps the UID unchanged.
                card1=card1, addr1=addr1, d1=None if d1n is None else dt / 86400 - d1n,
                card6="credit", amount=round(amount, 2), currency="USD", product_cd="W",
                transaction_dt=dt,
            )
            r = client.post("/transaction", json=payload, headers=headers)
            body = r.json()
            if r.status_code != 201:
                sys.exit(f"Submit failed: {r.status_code} {body}")
            print(f"#{i} amount {payload['amount']:>10.2f} -> {body['decision'].upper():<5} "
                  f"risk {body['risk_score']:.2f}  case {body['case_id']}")
            last = body
        print(f"\nExplanation of the last decision:\n  {last['explanation']}\n")

        other = client.post("/transaction", json=dict(payload, card1=card1 + 1), headers=headers)
        print(f"Submitting for a DIFFERENT card as this customer -> {other.status_code} {other.json()['detail']}\n")

        inv = login(client, "investigator1@example.invalid", "investigator")
        cases = client.get("/cases", headers=inv).json()
        print(f"Investigator sees {len(cases)} open case(s); highest risk first: "
              f"{[(c['case_id'], c['decision'], round(c['risk_score'], 2)) for c in cases[:3]]}")
        if last["case_id"] is None:
            print("The last transaction opened no case (it was allowed), so no feedback step.")
            return
        feedback = client.post(
            f"/cases/{last['case_id']}/feedback",
            json={"label": "fraud", "notes": "demo: confirmed with cardholder"}, headers=inv,
        )
        print(f"Feedback on case {last['case_id']} -> {feedback.status_code} {feedback.json()}")
        again = client.post(f"/cases/{last['case_id']}/feedback", json={"label": "fraud"}, headers=inv)
        print(f"Second feedback on the same case -> {again.status_code} {again.json()['detail']}")


if __name__ == "__main__":
    main()
