"""Network Intelligence (thin): shared-device graph, metrics, score, batch, signal."""

from __future__ import annotations

from datetime import datetime, timezone

import pytest
from passlib.hash import bcrypt

from agents.ingestion import process_transaction
from agents.network_intelligence import (
    build_customer_graph,
    compute_scores,
    network_score,
    network_signal,
    run_network_batch,
)
from agents.orchestrator import run_pipeline
from agents.uid import clean_component, compute_uid
from db.models import (
    Account,
    Customer,
    Device,
    DeviceCustomerLink,
    DecisionEnum,
    NetworkRiskScore,
)

DAY = 86400
NOW = datetime(2017, 12, 10, tzinfo=timezone.utc)
_FAST_HASH = bcrypt.using(rounds=4).hash("pw")


def _customers(session, n):
    ids = []
    for i in range(n):
        c = Customer(synthetic_uid=f"u{i}", name=f"c{i}", email=f"c{i}@example.invalid", hashed_password=_FAST_HASH)
        session.add(c)
        session.flush()
        ids.append(c.customer_id)
    return ids


def _share(session, fingerprint, customer_ids):
    """One device linked to every customer in customer_ids."""
    device = Device(device_fingerprint=fingerprint, device_type="mobile", first_seen_at=NOW, last_seen_at=NOW)
    session.add(device)
    session.flush()
    for cid in customer_ids:
        session.add(DeviceCustomerLink(device_id=device.device_id, customer_id=cid, first_seen_at=NOW, last_seen_at=NOW))
    session.flush()


def test_triangle_has_degree_two_clustering_one_and_score_075(db_session):
    a, b, c = _customers(db_session, 3)
    _share(db_session, "d1", [a, b, c])  # one device used by all three => fully connected

    scores = compute_scores(build_customer_graph(db_session))

    for node in (a, b, c):
        assert scores[node]["degree"] == 2 and scores[node]["clustering"] == 1.0
        assert scores[node]["component_size"] == 3
        assert scores[node]["score"] == pytest.approx(0.75)


def test_path_graph_scores_the_middle_customer_higher(db_session):
    a, b, c = _customers(db_session, 3)
    _share(db_session, "d1", [a, b])
    _share(db_session, "d2", [b, c])

    scores = compute_scores(build_customer_graph(db_session))

    assert scores[b]["degree"] == 2 and scores[b]["clustering"] == 0.0
    assert scores[b]["score"] == pytest.approx(0.5)
    assert scores[a]["score"] == pytest.approx(0.25) and scores[c]["score"] == pytest.approx(0.25)


def test_customers_with_only_private_devices_are_absent(db_session):
    a, b, loner = _customers(db_session, 3)
    _share(db_session, "shared", [a, b])
    _share(db_session, "private", [loner])  # a device only one customer ever used

    graph = build_customer_graph(db_session)

    assert loner not in graph and a in graph and b in graph


def test_score_is_capped_at_one():
    assert network_score(degree=5, clustering=0.0) == 1.0
    assert network_score(degree=0, clustering=0.0) == 0.0
    assert 0.0 <= network_score(degree=3, clustering=0.5) <= 1.0


def test_batch_writes_one_row_per_connected_customer_with_metrics(db_session):
    a, b, c, loner = _customers(db_session, 4)
    _share(db_session, "d1", [a, b, c])

    assert run_network_batch(db_session) == 3

    rows = db_session.query(NetworkRiskScore).all()
    assert {r.customer_id for r in rows} == {a, b, c}
    assert loner not in {r.customer_id for r in rows}
    assert rows[0].graph_metrics == {"degree": 2, "clustering": 1.0, "component_size": 3}


def test_latest_row_wins_and_history_is_kept(db_session):
    a, b, c = _customers(db_session, 3)
    _share(db_session, "d1", [a, b])
    run_network_batch(db_session)
    first = network_signal(db_session, a).score  # degree 1, clustering 0 -> 0.25

    _share(db_session, "d2", [a, c])  # a now links to b AND c
    run_network_batch(db_session)

    assert network_signal(db_session, a).score > first
    assert db_session.query(NetworkRiskScore).filter_by(customer_id=a).count() == 2  # history kept


def test_signal_abstains_without_a_score_and_explains_with_one(db_session):
    a, b = _customers(db_session, 2)
    assert network_signal(db_session, a).abstained
    assert network_signal(db_session, a).reason == "no network score computed"

    _share(db_session, "d1", [a, b])
    run_network_batch(db_session)
    signal = network_signal(db_session, a)
    assert not signal.abstained and signal.score == pytest.approx(0.25)
    assert signal.reason == "linked to 1 other customers via shared devices"


def test_two_customers_sharing_a_real_device_through_ingestion_get_linked(db_session):
    """End to end with the REAL linking logic (agents/device_identity.py): a specific
    DeviceInfo + browser is device-intrinsic, so two customers using it get linked."""
    device = dict(device_type="mobile", device_info="SM-G960F Build/R16NW", browser="chrome 63.0")
    for card1 in (1000, 2000):
        process_transaction(
            db_session, card1=card1, addr1=300.0, d1=5.0 + 10, card6="credit", amount=10.0,
            currency="USD", product_cd="W", transaction_dt=10 * DAY, **device,
        )

    graph = build_customer_graph(db_session)

    assert graph.number_of_nodes() == 2 and graph.number_of_edges() == 1


# ---- in the pipeline ----

def _pre_create_customer(session, card1, dt=10 * DAY):
    uid = compute_uid(card1, 300.0, 5.0 + dt / DAY, dt / DAY)
    customer = Customer(
        synthetic_uid=uid, billing_region=clean_component(300.0), name="c",
        email=f"{uid}@example.invalid", hashed_password=_FAST_HASH,
    )
    session.add(customer)
    session.flush()
    session.add(Account(customer_id=customer.customer_id, account_number=f"ACCT-{uid}", account_type="credit"))
    session.flush()
    return customer.customer_id


def _run(session, card1, dt=10 * DAY):
    return run_pipeline(
        session, card1=card1, addr1=300.0, d1=5.0 + dt / DAY, card6="credit", amount=10.0,
        currency="USD", product_cd="W", transaction_dt=dt,
    )


def test_a_high_network_score_raises_risk_and_is_explained(db_session):
    customer_id = _pre_create_customer(db_session, 1000)
    db_session.add(
        NetworkRiskScore(customer_id=customer_id, score=0.75, graph_metrics={"degree": 2}, computed_at=NOW)
    )
    db_session.flush()

    out = _run(db_session, 1000)

    assert out["assessment"].risk_score == pytest.approx(0.8 * 0.75)  # network weight 0.8
    assert out["assessment"].decision == DecisionEnum.FLAG
    text = out["assessment"].explanation_text
    assert "linked to 2 other customers via shared devices" in text.split(" Evidence: ")[0]
    assert "network 0.75" in text


def test_a_customer_without_a_network_score_is_unaffected(db_session):
    _pre_create_customer(db_session, 3000)

    out = _run(db_session, 3000)

    assert out["assessment"].decision == DecisionEnum.ALLOW
    assert "network abstained (no network score computed)" in out["assessment"].explanation_text
