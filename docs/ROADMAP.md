# Build checklist — weeks 1–8

Companion to `DECISIONS.md` (the *why*) — this is the *what's left*. Check items off as you go; commit message conventions follow ADR-007 (one commit per completed unit of work).

---

## Week 1 — Ingestion Agent + API Gateway + DB models

- [x] SQLAlchemy models — 14 entities: the 13 from the Lab5 ERD plus `DeviceCustomerLink` (ADR-014) (`db/base.py`, `db/models.py`, `db/session.py`)
- [x] **Push `db/` files to the repo**
- [x] `agents/uid.py` — synthetic customer identity (ADR-011; amended in Week 3 to use D1n)
- [x] `api/main.py` — FastAPI app entry point; calls `init_db()` at startup
- [x] `api/routes/transactions.py` — `POST /transaction` endpoint accepting a raw transaction payload
- [x] `agents/ingestion.py` — validates incoming data, enriches with account/device history
- [x] `scripts/seed_db.py` — seeds sample customers, accounts, devices, merchants so there's something to enrich against
- [x] `tests/test_agents/test_ingestion.py` — valid input, malformed input, transaction with no device
- [x] `tests/test_api/test_transactions.py` — endpoint returns correct status/shape
- [x] Commit: schema + ingestion + API gateway as one or two units of work
- [ ] QnA checkpoint: validation/enrichment logic, why FastAPI, request/response model shape

## Week 2 — Rule Compliance + Device Trust

- [x] `agents/rule_compliance.py` — velocity and amount checks; writes `RuleViolation` rows. The geo/billing rule was rejected as structurally unreachable, not deferred (ADR-015)
- [ ] Concrete rule thresholds decided and written down (not left vague) — values exist only as constants in `rule_compliance.py`; still need a section in `DECISIONS.md` or a config file
- [x] `agents/device_trust.py` — device reuse count, first-seen flag, device age scoring (ADR-002: rule-based, not ML)
- [x] `agents/device_identity.py` — shared fingerprint + `DeviceCustomerLink` helper used by both ingestion and seeding (ADR-014)
- [ ] Tests for both — files written (`test_rule_compliance.py`, `test_device_trust.py`, `test_device_timestamps.py`); tick once `uv run pytest` is green locally
- [ ] Commit — Week 2 code is committed; the tests and the datetime fix (ADR-016) are not yet
- [ ] QnA checkpoint: why Device Trust is statistical not ML, how thresholds were chosen

## Week 3 prep — do before `ml/train_isolation_forest.py`

- [x] UID normalized to D1n (ADR-011 amendment)
- [x] `transaction_dt` accepted by the API + ingestion; `REFERENCE_START` is a single source of truth in `agents/uid.py`
- [x] Device timestamps from transaction time (`seen_at`) + `UTCDateTime` ORM type (ADR-016)
- [x] Delete `fraud_detection.db`, re-seed, run `uv run python -m scripts.check_seed` — must print 0 bad devices
- [x] Run `uv run python -m scripts.prior_txn_buckets` and record the table — result: >=3 priors = 37.8% of transactions, 46.1% of fraud
- [ ] Cold-start rule decided (abstain below 3 prior transactions) — decision made; write it up as ADR-017 (text in `DOC_EDITS_2.md`)
- [ ] ADR-013 and ADR-014 amendments added (append, don't overwrite)
- [ ] Behavioral Analysis feature list written down, limited to what exists at serving time: the `Transaction` row plus Rule Compliance / Device Trust outputs (`D` and `V` columns are not in the payload or the DB)

## Week 3 — Behavioral Analysis

> **Order change (agreed):** the Week 4 orchestrator + Risk Synthesis are built *before* this agent so a working end-to-end demo exists early. Behavioral Analysis then lands as a new node and one extra `Signal` into Risk Synthesis (ADR-018). Staged model plan: global Isolation Forest first (time-boxed ~2 days); add a supervised XGBoost on the same features only if PR-AUC on the scorable slice is under ~2x its base rate (~4.3%).

- [ ] `ml/train_isolation_forest.py` — one global Isolation Forest over per-UID, time-gated features (ADR-012). Per-customer forests rejected: 8–150 transactions per UID is too few to isolate anything, and `ModelVersion.artifact_path` assumes one model per version
- [ ] First trained artifact saved to `ml/artifacts/` (gitignored)
- [ ] First `ModelVersion` row inserted — `trained_at`, `hyperparameters`, `metrics`, `artifact_path` all populated for real
- [ ] `agents/behavioral_analysis.py` — loads the model, scores incoming transactions, follows the cold-start ADR for thin-history UIDs
- [ ] Evaluation against held-out labeled IEEE-CIS data — PR-AUC plus precision/recall/F1/false-positive rate at a threshold chosen on validation (not test); UID-based split plus a time-based holdout; coverage (share of transactions scorable) reported alongside; all recorded in `ModelVersion.metrics`
- [ ] Tests: score always in valid 0–1 range (or abstains per the cold-start ADR), handles missing features without crashing
- [ ] Commit
- [ ] **Deepest QnA session of the build** — Isolation Forest intuition, why a global model over per-UID features beat per-customer forests, what each metric means and why false-positive rate matters specifically for fraud

## Week 4 — Risk Synthesis + orchestrator wiring

- [ ] `agents/orchestrator.py` — LangGraph state graph: Ingestion → Rule Compliance → Device Trust → Risk Synthesis. Edges are sequential on purpose: nodes share one SQLAlchemy Session, which isn't thread-safe, and LangGraph runs fan-out branches in threads (ADR-018). Behavioral Analysis is added as a node after Week 3
- [ ] `agents/history.py` — `count_prior_transactions` + `MIN_PRIOR_FOR_BEHAVIORAL = 3` (cold-start constant, ADR-017)
- [ ] `agents/risk_synthesis.py` — weighted noisy-OR fusion; abstaining agents skipped and named in the explanation; thresholds allow <0.35 / flag / block >=0.70 (starting points, ADR-018)
- [ ] Writes `RiskAssessment` rows (`model_version_id` stays NULL until a trained model contributes)
- [ ] Wire `POST /transaction` to `run_pipeline` (replace the direct `process_transaction` call) and return decision, score and explanation
- [ ] **First end-to-end demo** — submit a transaction through the API, get a real decision back
- [ ] `scripts/replay_eval.py` — replay the seeded customers through the pipeline; record the rules+device-only baseline (recall/precision vs isFraud) before Behavioral Analysis exists
- [ ] Integration tests: `test_risk_synthesis.py` + `test_orchestrator.py` (files delivered; tick once green locally)
- [ ] Commit
- [ ] QnA checkpoint: LangGraph state-passing mechanics, fusion formula reasoning, threshold choices

## Week 5 — Network Intelligence + checkpoint

- [ ] `agents/network_intelligence.py` — networkx graph from shared device/address (ADR-003: classical metrics, not a GNN)
- [ ] `scripts/run_network_batch.py` — the APScheduler job definition
- [ ] Writes `NetworkRiskScore` rows periodically
- [ ] Risk Synthesis updated to read the latest score for a customer (defaults to neutral before the first batch run completes)
- [ ] **Checkpoint: go/no-go on Investigator Assistant** — evaluate actual weeks 1–4 progress, write the decision into `DECISIONS.md` either way (ADR-009)
- [ ] Tests: graph construction on sample data, score computation
- [ ] Commit
- [ ] QnA checkpoint: degree/clustering-coefficient as fraud signals, why classical graph metrics over a GNN

## Week 6 — Explanation + Case Management

- [ ] `agents/explanation.py` — instant templated reason (sync) + richer reason via Ollama (async)
- [ ] Ollama integration tested — `llama3.1:8b-instruct` pulled and actually called, latency checked
- [ ] `agents/case_management.py` — opens a `FraudCase` only when decision is flag or block
- [ ] Tests: template correctness, case only created under the right condition
- [ ] Commit
- [ ] QnA checkpoint: sync/async split reasoning (ADR-004), how the LLM prompt is constructed

## Week 7 — Dashboard + auth

- [ ] Real JWT auth for Customer and Investigator roles; Admin as a simplified flag (ADR-010) — no full login plumbing for Admin
- [ ] `dashboard/app.py` — Streamlit: live transaction feed, per-agent status, investigator case queue, analytics
- [ ] Investigator case review + `Feedback` submission wired end-to-end into the database
- [ ] Integration testing across the full stack (API + agents + dashboard)
- [ ] Commit
- [ ] QnA checkpoint: auth flow, how the dashboard reads/writes case data

## Week 8 — Tests, CI, polish

- [ ] Expand pytest coverage across all 8 agents and the API layer
- [ ] `.github/workflows/` — one minimal CI workflow, runs pytest on push
- [ ] **Resolve the retraining-threshold open item** — pick an actual number, write it into `DECISIONS.md`
- [ ] `DECISIONS.md` finalization pass — confirm it reflects what was actually built, not just what was planned
- [ ] Demo rehearsal — practice explaining every agent, not just running the demo

---

## Week 9 (buffer, not covered above)

Absorbs holiday/lab disruption. If Investigator Assistant was greenlit at the week-5 checkpoint and isn't done yet, it lands here.

---

## Housekeeping (not blocking)

- [ ] StarUML ERD still shows 13 entities; the schema has 14 (`DeviceCustomerLink`) — update before the next diagram-based submission
