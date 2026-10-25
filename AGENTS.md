# Project context for AI coding agents

Multi-agent real-time fraud detection (VIT Chennai SE lab project). FastAPI backend, LangGraph orchestrator, SQLite, a local XGBoost model, and a Next.js website exported as static files and served by the same FastAPI process. Python 3.11+, managed with `uv`. Windows + PowerShell (chain commands with `;`, not `&&`).

## Run it
```
uv sync
uv run pytest                       # all tests must stay green
cd web; npm install; npm run build; cd ..   # writes web/out (gitignored)
uv run uvicorn api.main:app         # site + API at http://127.0.0.1:8000
uv run python -m scripts.demo_reset --yes   # rebuild the demo DB (slow, DESTROYS fraud_detection.db)
```
Demo logins (password `ChangeMe123!`): customer `seed.customer.00001@example.invalid`, investigator `investigator1@example.invalid`.

## Layout
- `agents/` 8 agents + `orchestrator.py` (LangGraph). `api/` FastAPI app, `api/routes/`, JWT in `api/auth.py`.
- `db/` SQLAlchemy models. `ml/` training. `scripts/` seed, eval, batch and demo scripts. `tests/` pytest.
- `web/` the website (Next.js static export). `docs/DECISIONS.md` is the ADR log: the source of truth for WHY.
- `data/` and `ml/artifacts/` are gitignored (dataset and trained model are not in the repo).

## Pipeline
ingestion -> rule_compliance -> device_trust -> behavioral_analysis -> risk_synthesis -> explanation -> case_management.
Network intelligence is a separate batch (`scripts/run_network_batch.py`); risk synthesis only reads its latest score.
Fusion = weighted noisy-OR over agents that produced a signal; abstaining agents (score None) are skipped.
Weights: rules 1.0, device 0.8, behavioral 1.0, network 0.8. Decisions: allow < 0.35, flag 0.35 to 0.70, block >= 0.70.
Edges are sequential ON PURPOSE: nodes share one SQLAlchemy Session (not thread-safe).

## Rules that must not be broken
1. Do NOT change scoring: thresholds, weights, rule limits, model features, training code, calibration, `agents/risk_synthesis.py`, `agents/behavioral_features.py`. They are tied to ADRs and tests.
2. Do NOT edit `docs/DECISIONS.md` or ADR text. Propose changes in your report instead.
3. Customers must NEVER see a risk score, explanation, signals, case id or the words flag/block. Customer responses are `approved / under_review / declined` plus a message only (ADR-028). Investigators see full detail.
4. Time is transaction-driven and UTC-aware (ADR-016). Never use the wall clock for transaction timing.
5. Per-customer features are time-gated: only EARLIER transactions (ADR-012). Training and serving share one feature function.
6. Agents flush, they never commit. The API route owns the transaction.
7. `isFraud` is never stored in the database or given to any agent.
8. Auth surface is frozen: customer and investigator JWT only. Admin is an unauthenticated read-only demo page by design (ADR-010).
9. Do not add features, dependencies or refactors that were not asked for. The owner wants a working, defensible project, not more scope.
10. Never commit `data/`, `ml/artifacts/`, `fraud_detection.db`, `web/out`, `node_modules` or secrets. Never run `demo_reset` unless told to.

## Currency and identity facts (easy to get wrong)
- Database, model and API are in dataset dollars (USD). The website shows rupees at a fixed demo rate of 95 INR per USD (`web/lib/currency.ts`, ADR-029); rupee input is converted to dollars before it is sent.
- Customer identity is a synthetic UID `card1-addr1-D1n` (ADR-011). The website never asks for it: `POST /transactions/me` builds card, region, D1 and a simulated time from the logged-in customer.
- The transaction clock is simulated (latest transaction + 1 hour), so dates fall in 2017-18 (ADR-016, 023).
- Product codes W, C, R, H, S are anonymized IEEE-CIS codes with undisclosed meaning. Never invent labels for them.
- The card type comes from the card on file; the website does not let a customer change it (ADR-030).
- The amount rule compares with the customer's MEDIAN of earlier amounts (ADR-030).

## Known and accepted limitations (do not "fix" these silently)
- A rules-only hit scores at most 0.60, so it flags but never blocks without another agent (ADR-022).
- Device and network agents often abstain: only ~17% of seeded transactions carry a device.
- Investigator feedback is counted (threshold 100) but does not retrain the model (ADR-025).
- Legacy `POST /transaction` returns the full score to a customer token; it is hidden from /docs and kept for scripts/tests.
- `GET /admin/overview` has no auth (local demo only).

## Working style
Report what you actually observed, with exact values and screenshots. If something is ambiguous, ask instead of guessing. If a test fails, show the failure; do not weaken or delete the test.
