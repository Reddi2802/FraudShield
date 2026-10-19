# Architecture Decision Log

This log records why this system is built the way it is. The original SE lab submissions (Lab 1–5) are submitted separately via MS Teams and not duplicated here — this file is the standalone record of the reasoning behind the current design, for anyone reading the repo without access to those submissions.

---

## ADR-001 — Pivot from single-model pipeline to multi-agent architecture

**Context:** The initial project brief (Lab 1) proposed a two-stage pipeline — rule engine, then Isolation Forest + XGBoost fused into a risk score. The course instructor approved the fraud-detection concept on the condition that the project incorporate distinct, purpose-built agents, added incrementally.
**Decision:** Rebuilt around a LangGraph-orchestrated multi-agent architecture, where each fraud signal (rules, behavioral anomaly, device trust, network risk) is computed by an independent agent and combined by a Risk Synthesis Agent, rather than one model producing a single score.
**Why this works, not just complies:** A graph-of-agents lets a new agent be added as a new node without rewriting the existing pipeline — which matters directly, since new agents kept being required lab over lab.

## ADR-002 — Device Trust Agent scored statistically, not with ML

**Context:** IEEE-CIS Fraud Detection has device-related columns (`DeviceInfo`, `id_*`) but no ground-truth label for "is this device trustworthy" — training a supervised model here would mean fabricating labels.
**Decision:** Score device trust via explicit signals — device reuse count across distinct customers, first-time-seen flag, device age — rather than a trained model.
**Rejected alternative:** An unsupervised device-anomaly model. Rejected because there's no way to validate it against ground truth, and an unvalidated model is worse than a transparent rule set for an explainability-focused system.

## ADR-003 — Network Intelligence Agent uses classical graph metrics, not a GNN

**Context:** IEEE-CIS has no explicit customer relationship graph. One can be constructed from co-occurrence of shared devices, addresses, or email domains across anonymized accounts.
**Decision:** Build the co-occurrence graph with `networkx`, score customers using degree and clustering-coefficient as fraud-ring signals, computed as an async batch job (APScheduler) rather than per-transaction.
**Rejected alternative:** A graph neural network. Explicitly out of scope — no labeled ring/fraud-network ground truth exists in the dataset, and a GNN adds research-level complexity without a way to validate it, which is a bad trade for a semester project. Classical graph metrics are auditable and explainable, which fits the project's core requirement better than a black-box GNN would.

## ADR-004 — Explanation split into sync rule-based + async local LLM

**Context:** Lab 2's NFR requires a decision within 500ms including the LLM call. On local hardware (RTX 4050, 6GB VRAM) with no paid API budget, a real LLM call realistically takes 1–3 seconds.
**Decision:** Risk Synthesis returns a decision immediately with a fast, templated rule-based explanation (sub-150ms). A richer natural-language explanation generates asynchronously via a local Ollama model and attaches to the record shortly after.
**Why this is a better design, not a workaround:** Real fraud systems don't block a transaction decision on text generation. This also produces a stronger interview talking point than the original spec did.

## ADR-005 — Local LLM (Ollama) instead of a hosted API

**Context:** No budget for paid API usage; hardware supports local quantized inference.
**Decision:** `llama3.1:8b-instruct` via Ollama, run entirely on-device.
**Consequence:** No transaction data ever leaves the machine — a genuine answer to data-privacy questions a fintech-adjacent project should expect in interviews.

## ADR-006 — uv instead of pip/venv

**Decision:** Dependency management via `uv` (`pyproject.toml` + `uv.lock`) rather than `requirements.txt`.
**Why:** Faster installs, reproducible lockfile, single source of truth — avoids the `requirements.txt`/lockfile drift that existed in the repo's earlier (discarded) structure.

## ADR-007 — Commit cadence tied to units of work, not sessions

**Context:** The instructor checks commit history periodically. Early commits were large and infrequent.
**Decision:** One commit per completed agent or feature, mapped to the sprint structure already defined in Lab 3, rather than one commit per working session.

## ADR-008 — Core scope is all 8 agents; "Core vs. Extension" tiering retired

**Context:** An earlier internal roadmap (pre-Lab7) split the 8 agents into a "Core" tier (6 agents) and an "Extension" tier (Device Trust, Network Intelligence, treated as optional/later). Lab7's component diagram was then submitted with Device Trust and Network Intelligence fully wired into the orchestrator's coordination and interface contracts (`INetworkRiskScore`).
**Decision:** All 8 agents are core scope. The Core/Extension split is retired as of this ADR. What remains genuinely optional is scoped separately below (ADR-009), not folded into the 8-agent set.
**Why:** A graded, submitted diagram is a commitment. Calling a diagrammed, interface-defined agent "optional" internally creates a document that contradicts the artifact it's supposed to explain — a bad look if a reviewer or interviewer cross-references the repo against the lab submissions.

## ADR-009 — Monitoring Agent cut; Investigator Assistant Agent conditional on a week-5 checkpoint

**Context:** Lab5 explicitly scoped Admin console features (rule config, investigator management, agent-log viewing, drift monitoring) and semantic case search as actor-level capabilities, not standalone system modules to be diagrammed. The README's agent table nonetheless listed a "Monitoring Agent (planned)" and "Investigator Assistant Agent (stretch)" alongside the real 8, which is not what the diagrams committed to.
**Decision:**
    - **Monitoring Agent: dropped.** Not built, not diagrammed, not listed as a project agent. Drift monitoring, if mentioned at all, is a "future work" line, not a table entry implying active development.
    - **Investigator Assistant Agent (FAISS semantic case search): conditional.** All 8 core agents are built and demonstrable end-to-end first, no exceptions. At the **week-5 checkpoint**, evaluate actual progress against the plan below. Only if the 8-agent pipeline is on track does Investigator Assistant get scheduled into the remaining weeks. This is a scheduled decision point, not an open-ended "if time allows."
**Why:** "If time allows" is how scope drifted before (new agent nearly every lab). A dated checkpoint with a concrete precondition (8 agents done) replaces that pattern with an actual decision rule.

## ADR-010 — RBAC scoped to where it gates real pipeline behavior

**Context:** Admin does not correspond to any of the 8 diagrammed agents — Lab5 treats Admin capabilities (configure rules, manage investigators, view logs) as dashboard-level actor conveniences, not system modules. Customer and Investigator roles, by contrast, gate real pipeline actions: submitting a transaction, reviewing/resolving a fraud case.
**Decision:** Real JWT-based auth (`python-jose` + `passlib`) is implemented for **Customer** and **Investigator** roles, since these gate actual agent-pipeline behavior. **Admin** is implemented as a simplified role flag — sufficient to demo an admin view — without full login/token-verification plumbing behind it.
**Rejected alternative:** Full JWT RBAC across all three roles. Rejected because Admin's capabilities are not exercised by any agent in the pipeline; building real auth infrastructure for a role with no corresponding system logic spends time budget on infrastructure that doesn't demonstrate the project's actual subject matter (multi-agent fraud reasoning), inside a fixed ~8-week build window.

## ADR-011 — Synthetic UID for customer identity (IEEE-CIS has no native key)

UID = card1+addr1+D1, chosen for consensus and simplicity; revisit at week 3 if per-UID transaction-count distribution shows pathological fragmentation or collision.
Observed at seed time: high-count UID collisions are concentrated in rows with missing addr1 and D1=0 — e.g. one UID matched 7,198 rows under this pattern. Confirms the predicted collision risk; the [8,150] seeding range (see scripts/seed_db.py) was chosen specifically to exclude these.

**Amendment (Week 3):** Raw `D1` is a tenure counter — it advances by one for every day that passes — so using it directly gave the same card a different UID on different days and fragmented single customers. UID is now `card1 + addr1 + D1n`, where `D1n = floor(TransactionDT/86400 - D1)`, a stable per-card anchor. Real-data check before switching: single-transaction UIDs fell from 73.3% to 57.4% and the largest collision outlier from 7,198 to 1,414 rows. `agents/uid.py` owns `REFERENCE_START`, the single source of truth for the TransactionDT epoch, and callers must supply the transaction's day offset (`transaction_dt` in the API). Residual collisions remain (the largest UID still spans 1,414 rows), so the [8,150] seeding window (ADR-013) stays.

## ADR-012 — Per-UID features must be time-gated, not full-history

**Context:** Behavioral Analysis (ADR-011's UID) needs per-customer aggregate features (avg transaction amount, D-column stats, transaction count) to score behavior. Computing these from a customer's *entire* transaction history — including transactions after the one being scored — leaks future data into the present. This doesn't error out; it just produces misleadingly strong validation scores that won't hold up in production, where future transactions don't exist yet at scoring time.

**Decision:** Per-UID aggregates are computed only from transactions with an earlier `TransactionDT` than the one being scored (expanding window, ordered by time, per UID). Train/validation splits for Behavioral Analysis are done by UID, not by row — a UID's transactions go entirely into one split, never both.

**Rejected alternative:** Static full-history aggregates per UID. Simpler, but leaks future information into past predictions — fine for a one-off Kaggle submission, wrong for a system meant to score transactions in real time.

**Consequence:** Feature computation needs a time-ordered expanding aggregation per UID, not a single groupby. This matches how a real production system actually works — it never has a customer's future transactions when scoring a live one.

**Amendment (Week 3):** the train/validation split for Behavioral Analysis is chronological (train on the earliest 55% of TransactionDT, validate on the next 15%, test on the last 30%) instead of by UID. Time-gated per-UID features already prevent leakage within a UID; a time split additionally tests drift across the dataset window and is the stricter of the two (ADR-019).

## ADR-013 — Seed data sampled from UIDs with 8–150 transactions, not the full population

**Context:** Uniform sampling over all 246,418 UIDs mostly picks thin-history customers (median=1 transaction) — no baseline for Behavioral Analysis (week 3) to learn from. The same distribution's high end is worse: the top UID matched 7,198 rows, concentrated around missing `addr1` + `D1=0` — a card1+addr1+D1 collision merging many different transactions into one UID, not one very active customer.

**Decision:** `scripts/seed_db.py` samples its 1,500 customers only from UIDs with 8–150 transactions. Floor excludes thin-history UIDs; ceiling excludes collision-driven outliers (150 ≈ 1 txn/day sustained over IEEE-CIS's ~6-month window, already generous for a real shopper).

**Rejected alternative:** Uniform sampling (original implementation). Rejected because it's exposed to both problems at once — mostly thin customers, with no protection against collision outliers either.

**Why this isn't a training-data change:** Both bounds are seeding/demo-data policy only. `ml/train_behavioral.py` (week 3, ADR-019) trains directly against the unfiltered raw CSV, per ADR-012.

**Amendment (Week 3, after the D1n fix — see ADR-011):** With D1n UIDs the loaded data has 217,850 distinct UIDs (median 1, mean 2.71, max 1,414), and the [8,150] pool grew from 6,739 to 14,504 UIDs. Bounds are unchanged. The 1,500 seeded customers carry 21,832 transactions (8–123 per customer, median 11). The figures above (246,418 UIDs, 7,198-row outlier) describe the pre-fix raw-D1 UID and are kept as the historical record. The seeded sample is deliberately history-rich: 79.4% of seeded transactions have at least 3 prior transactions, against 37.8% across the full dataset, so demo coverage overstates real-world coverage.

## ADR-014 — Device identity: many-to-many schema + device-intrinsic fingerprinting

**Context:** Week 1's Device.customer_id was a single FK, and the device fingerprint (`f"{uid}:{type}:{info}"`) baked the customer's synthetic_uid into the key itself — making cross-customer device sharing (the actual fraud-ring precursor signal ADR-002 was written around) structurally unobservable, not just unimplemented.

**Decision:** Device<->Customer changed to many-to-many via a new DeviceCustomerLink table (14 entities total, up from the Lab5-diagrammed 13 — not yet reconciled in the StarUML diagram). Fingerprint logic (agents/device_identity.py, shared between ingestion.py and seed_db.py) now builds a device-intrinsic fingerprint (DeviceInfo + id_31 browser string) when both are present and DeviceInfo isn't one of 7 generic OS-only buckets (Windows, iOS Device, MacOS, Trident/7.0, rv:11.0/57.0/59.0); otherwise falls back to the original customer-scoped scheme (excluding browser from that fallback key specifically — an earlier version included it and fragmented ~75% of generic-device customers across browser-version churn before being caught and fixed).

**Evidence (real data, not assumed):** Specific DeviceInfo+browser combinations show median 1 distinct UID per fingerprint (2,251 of 2,351 fingerprints, 95.7%) — genuine identity signal. Generic buckets show median 15, max 2,030 distinct UIDs per fingerprint — unusable as identity, would manufacture false cross-customer links if not excluded. Seeded result: 3,253 distinct devices (down from 3,565 under the old scheme — net fragmentation reduction, as expected), 158 linked to more than one customer.

**Rejected alternative:** Including browser in the fallback fingerprint. Technically simpler, but browser-version churn across a single customer's own sessions is common and not a "new device" — doing this inflated the seeded device count to 5,175 before being caught via a sanity check (the count should drop under merging, not rise) and fixed.

**Amendment (Week 3):** The seeded figures above (3,253 devices, 158 linked to more than one customer) were measured under raw-D1 UIDs and a different sampled population, so they are not directly comparable. Re-seeded under D1n UIDs: 1,359 distinct devices, 112 linked to more than one customer, with a device present on only 17.5% of seeded transactions (3,831 of 21,832) because most IEEE-CIS transactions have no identity row. `Device` and `DeviceCustomerLink` first/last-seen timestamps now come from the transaction's own timestamp rather than the wall clock (ADR-016).

## ADR-015 — Billing/geo rule rejected (structural, not deferred)

**Context:** A billing-address-mismatch rule was planned for Rule Compliance. addr1 is part of synthetic_uid = card1+addr1+D1 — a transaction with a different addr1 resolves to a different customer before any mismatch comparison could run, making a per-transaction billing rule structurally unreachable, not just unimplemented.

**Decision:** No billing/geo rule, in Rule Compliance or anywhere else. Customer.billing_region is kept as profile/explanation-text context only, never a RuleViolation trigger.

**Rejected alternatives, both checked against real data before rejecting:** (1) Decoupling identity from addr1 to recover the rule — rejected: weakens the already-fragile 3-anchor UID (more collision risk) for a feature that, per (2), wouldn't produce good signal anyway. (2) Routing addr1 into Network Intelligence (Week 5) as a shared-attribute graph edge — rejected: addr1 has only 332 distinct values across 590K transactions; even at the most aggressive exclusion threshold, 88.7% of rows fall into generic high-degree buckets, versus 85.3% usable after the equivalent device-fingerprint exclusion. addr1 is a masked regional code, not a granular address — there's no specific-enough tail to recover, unlike DeviceInfo+browser.

## ADR-016 — Time is transaction-driven and always UTC-aware

**Context:** Replaying IEEE-CIS rows through the API stamps `submitted_at` from the optional `transaction_dt` (REFERENCE_START + seconds), but device first/last-seen timestamps were still `datetime.now()` — a 2026 device against 2017–2018 transactions, so Device Trust's `device_age` came out about −8 years. Separately, SQLite returns naive datetimes on reload while agents build aware-UTC values; mixing them raised `can't subtract offset-naive and offset-aware datetimes`, but only once a row had left the session's identity map — it passed short tests and would have crashed in a live-shaped flow. Rule Compliance and Device Trust had no dedicated tests, so neither was caught.

**Decision:** (1) `get_or_create_device_and_link` takes `seen_at`, passed from `submitted_at` by ingestion and by `scripts/seed_db.py`; first/last-seen use min/max so out-of-order rows can't corrupt them. (2) `db/base.py` maps every `Mapped[datetime]` to a `UTCDateTime` TypeDecorator that returns aware UTC on load and normalizes to UTC on write. (3) Dedicated tests for Rule Compliance, Device Trust and the replay timeline.

**Rejected alternative:** Normalizing with `.replace(tzinfo=...)` inside each agent. Every future agent (Case Management, Network Intelligence) would have to remember it; the type fixes it once.

**Consequence:** Existing seeded DB files must be deleted and re-seeded. `scripts/check_seed.py` verifies no device is first-seen after its first transaction.

## ADR-017 — Behavioral Analysis abstains below 3 prior transactions

**Status:** Superseded by ADR-019 — the supervised model scores every transaction, so the abstention rule is dropped. Kept as the historical record and for the bucket-table evidence.

**Context:** With D1n UIDs, 57.4% of UIDs are single-transaction. Behavioral Analysis scores a transaction against the customer's own time-gated history (ADR-012); with no history there is nothing to compare against. Measured on the raw CSV: transactions with at least 3 prior UID transactions are 37.8% of traffic and 46.1% of all fraud. Fraud rate rises from 2.8% (0 priors) to 4.9% (8+ priors); part of that rise is probably UID collisions merging customers into one heavy "customer".

**Decision:** Below 3 prior transactions the agent returns no score (abstains). Risk Synthesis fuses only the agents that produced a signal, and the explanation names the abstaining agent. Training and evaluation use only transactions with at least 3 priors, and metrics are reported together with coverage (the share of transactions scorable). The cutoff is `MIN_PRIOR_FOR_BEHAVIORAL` in `agents/history.py`; it matches Rule Compliance's own minimum history for the amount check.

**Rejected alternatives:** (1) A neutral 0.5 for thin history — injects a fake opinion into more than half of all fusions. (2) A cutoff of 1 prior — raises coverage to about 63% of transactions and 71% of fraud, but scores customers on a single data point.

**Consequence:** Rule Compliance and Device Trust carry the remaining ~54% of fraud. Revisit the cutoff if the Week 3 evaluation shows usable signal at 1–2 priors.

## ADR-018 — Fusion by weighted noisy-OR; sequential graph for DB-bound nodes

**Context:** Week 4 must turn heterogeneous signals into one score and a decision, and most transactions are missing some signal: no device info on ~82% of seeded transactions, and Behavioral Analysis abstains on thin history (ADR-017).

**Decision:** `risk = 1 − PRODUCT(1 − weight × score)` over agents that produced a signal; abstainers are skipped. Rule severity scores: low 0.2, medium 0.4, high 0.6. Device: shared by N customers = 0.30 + 0.15 per extra customer (cap 0.75); new device for a customer who already has history = 0.15. Weights: rules 1.0, device 0.8. Thresholds: allow < 0.35, flag 0.35–0.70, block ≥ 0.70. The LangGraph graph is sequential: ingestion → rule_compliance → device_trust → risk_synthesis.

**Rejected alternatives:** (1) A weighted average — a clean device would dilute a rule hit, and abstentions would need renormalizing. (2) A parallel fan-out of Rule Compliance and Device Trust — verified that LangGraph runs fan-out branches in worker threads, and both nodes share one SQLAlchemy Session, which is not thread-safe.

**Evidence (real data):** `scripts/replay_eval.py` replayed the 1,500 seeded customers (21,832 transactions, 968 fraud, 4.43% base rate) through Rule Compliance + Device Trust + Risk Synthesis. Flag+block covered 4.7% of transactions with recall 4.4% and precision 4.2% — no lift over the base rate. This is expected for hard-limit rules (velocity, amount, shared device), which are compliance checks rather than fraud rankers; ranking is delegated to Behavioral Analysis.

**Consequence:** Every number above is a starting point, not a tuned value. Behavioral Analysis and Network Intelligence plug in as extra `Signal`s with no change to the fusion.

## ADR-019 — Behavioral Analysis is a supervised XGBoost model that scores every transaction

**Context:** The roadmap planned an Isolation Forest (first per-customer, then global). Two measurements changed that. `scripts/replay_eval.py` showed Rule Compliance + Device Trust alone have no lift (flag+block precision 4.2% against a 4.43% base rate). `scripts/feature_signal.py` showed a gradient-boosted model on features available at serving reaches 4.1x PR-AUC lift (ROC-AUC 0.795) on all transactions and 3.6x on the slice with at least 3 prior transactions, versus 14.1x with extra C/D columns. Much of the signal is not history-based (ProductCD C 3.34x lift, W 0.58x; hour of day; amount), which an unsupervised anomaly detector cannot exploit and which exists for transactions with no history.

**Decision:** Behavioral Analysis is one XGBoost classifier (`scale_pos_weight`, no SMOTE) over eight features computed by one shared function for training and serving (`agents/behavioral_features.py`): amount, product_cd, card6, hour, prior_count, amt_ratio, amt_z, secs_since_last. All history features are time-gated (ADR-012). It scores every transaction; history features are simply missing below 3 prior transactions, which XGBoost handles natively, so ADR-017's abstention is superseded (the agent abstains only when no model is registered). The split is chronological (ADR-012 amendment). The probability is mapped to a 0-1 risk signal by a piecewise-linear map fitted on validation data only (median -> 0, 95th percentile -> flag threshold 0.35, 99th -> block threshold 0.70, 99.9th -> 1.0), so roughly the top 5% flag and the top 1% block on validation. Per-prediction feature contributions name the top drivers in the explanation.

**Rejected alternatives:** (1) Isolation Forest — unsupervised, ignores the labels, never measured on this data; stays a stretch item. (2) Per-customer models — 8-150 transactions per UID is too few. (3) Expanded C/D features — 14x versus 4x lift, but needs an API payload and storage change; deferred as a stretch item. (4) SMOTE — synthetic rows would break time-gating.

**Consequence:** Results are modest but real (about 4x lift expected). The probability is rank-calibrated, not probabilistically calibrated. Training and serving share one code path, checked by a parity test. The honest end-to-end number is the HELD-OUT table printed by `scripts/replay_eval.py`. After deleting and re-seeding the DB, run `uv run python -m ml.train_behavioral --register-only` to re-register the model (the artifact lives in gitignored `ml/artifacts/`).

**Results (first run on the full CSV, chronological split):** test period 177,162 rows (3.46% fraud): PR-AUC 0.140 (4.0x lift), ROC-AUC 0.789, coverage 100%. At the validation-chosen thresholds, flag covers 3.9% of transactions (precision 19.1%, recall 21.7%) and block 0.7% (precision 27.2%, recall 5.5%). End-to-end `replay_eval` on the 1,500 seeded customers, held-out period only (6,565 transactions, 278 fraud, 4.23% base rate): fraud rate allow 3.56%, flag 8.35%, block 20.2%; flag+block cover 10.4% of transactions with precision 10.1% (2.4x) and recall 24.8%; fused PR-AUC 0.104 (2.5x). The Rules + Device baseline had no lift (4.2% vs 4.43%). The held-out sample is small (278 fraud), so its lift carries wide uncertainty.

## ADR-020 — Explanation is a deterministic plain-language template; cases open only on flag/block

**Context:** Risk Synthesis already produced a technical evidence string, but it reads like a log line. ADR-004 splits explanation into an instant template and a slower local-LLM enrichment. The schema already holds FraudCase (UNIQUE per transaction), Feedback and Investigator, and the README promises a case_id in the API response.

**Decision:** (1) The Explanation Agent writes one plain-language sentence from STRUCTURED evidence (rule violations, the device signal, the Behavioral model's positive top drivers) and keeps the technical string after it in the same explanation_text field: Flagged for review: the amount is much higher than this customer's usual spend. Evidence: FLAG (risk 0.60). rules 0.60: .... Behavioral reasons appear only when behavioral risk is at least 0.20, at most 4 reasons are listed, and nothing is parsed out of text. It is instant and never blocks a decision. (2) The Case Management Agent opens an OPEN, unassigned FraudCase only for flag or block, once per transaction (idempotent), stamped with the transaction's own timestamp (ADR-016). (3) POST /transaction returns case_id, null for allowed transactions. (4) run_risk_synthesis_detailed returns the full RiskDecision so downstream agents consume signals, not strings.

**Rejected alternatives:** (1) LLM-generated explanations now — latency, local-hardware setup and failure modes for little demo value; stays a stretch item and would append to the template, not replace it. (2) A separate explanation column or table — needs a schema change for no benefit. (3) Case assignment logic — investigators pick cases up from the dashboard (Week 7). (4) Retraining from feedback here — a manual script with its own threshold decision in Week 8.

**Consequence:** Every decision carries a human-readable reason that names only evidence the system actually produced. The previous assertions that an explanation began with "ALLOW (risk 0.00)" now check for "Evidence: ALLOW (risk 0.00)" instead.

---

## Open items (revisit as the project progresses)

- Retraining trigger threshold (how many new `Feedback` labels before the Behavioral Analysis Agent retrains) — not yet finalized; to be set when the Behavioral Analysis / Case Management feedback loop is built.
- Week-5 checkpoint (ADR-009): go/no-go on Investigator Assistant Agent, decided against actual progress at that point, not in advance.
- Rule Compliance thresholds (velocity above 5 transactions per hour, amount above 3x own mean, global p99 fallback) are constants in code with no recorded rationale. `feature_signal` shows repeat-within-1h at 1.91x lift and amount-spike at 1.37x lift on the full data; record the chosen thresholds and their evidence here.
- Expanded feature set (C/D/dist1/card4 columns, ~14x lift in `feature_signal`) is a stretch item, decided only after the core pipeline is complete (needs an API payload and storage change plus a new ADR).
- Label delay: investigators confirm fraud with a lag, so a production retraining loop would leave a gap between the training window and the evaluation window. The current chronological split has no gap; note this as a known limitation.
