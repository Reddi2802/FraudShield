# Build checklist — weeks 1–8

Companion to `DECISIONS.md` (the *why*) — this is the *what's left*. Check items off as you go; commit message conventions follow ADR-007 (one commit per completed unit of work).

---

## Week 1 — Ingestion Agent + API Gateway + DB models

- [x] SQLAlchemy models — 13 entities from the Lab5 ERD (`db/base.py`, `db/models.py`, `db/session.py`)
- [x] **Push `db/` files to the repo** — built but not yet committed as of this checklist
- [ ] `api/main.py` — FastAPI app entry point; calls `init_db()` at startup
- [ ] `api/routes/transactions.py` — `POST /transaction` endpoint accepting a raw transaction payload
- [ ] `agents/ingestion.py` — validates incoming data, enriches with account/device history
- [ ] `scripts/seed_db.py` — seeds sample customers, accounts, devices, merchants so there's something to enrich against
- [ ] `tests/test_agents/test_ingestion.py` — valid input, malformed input, transaction with no device
- [ ] `tests/test_api/test_transactions.py` — endpoint returns correct status/shape
- [ ] Commit: schema + ingestion + API gateway as one or two units of work
- [ ] QnA checkpoint: validation/enrichment logic, why FastAPI, request/response model shape

## Week 2 — Rule Compliance + Device Trust

- [ ] `agents/rule_compliance.py` — velocity, amount, geo threshold checks; writes `RuleViolation` rows
- [ ] Concrete rule thresholds decided and written down (not left vague) — a config file or a section in `DECISIONS.md`
- [ ] `agents/device_trust.py` — device reuse count, first-seen flag, device age scoring (ADR-002: rule-based, not ML)
- [ ] Tests for both — rule triggers correctly, edge case of a transaction with no device
- [ ] Commit
- [ ] QnA checkpoint: why Device Trust is statistical not ML, how thresholds were chosen

## Week 3 — Behavioral Analysis

- [ ] `ml/train_isolation_forest.py` — per-customer Isolation Forest training
- [ ] First trained artifact saved to `ml/artifacts/` (gitignored)
- [ ] First `ModelVersion` row inserted — `trained_at`, `hyperparameters`, `metrics`, `artifact_path` all populated for real
- [ ] `agents/behavioral_analysis.py` — loads the model, scores incoming transactions
- [ ] Evaluation against held-out labeled IEEE-CIS data — precision/recall/F1/false-positive rate, recorded in `ModelVersion.metrics`
- [ ] Tests: score always in valid 0–1 range, handles missing features without crashing
- [ ] Commit
- [ ] **Deepest QnA session of the build** — Isolation Forest intuition, per-customer vs. global model choice, what each metric means and why false-positive rate matters specifically for fraud

## Week 4 — Risk Synthesis + orchestrator wiring

- [ ] `agents/orchestrator.py` — LangGraph state graph: Ingestion → [Rule Compliance, Behavioral Analysis, Device Trust] → Risk Synthesis
- [ ] `agents/risk_synthesis.py` — fusion logic and decision thresholds (allow/flag/block)
- [ ] Writes `RiskAssessment` rows tagged with `model_version_id`
- [ ] **First end-to-end demo** — submit a transaction through the API, get a real decision back
- [ ] Integration test: full graph run against a batch of sample transactions
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
