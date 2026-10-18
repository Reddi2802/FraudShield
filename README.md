# Multi-Agent AI System for Real-Time Financial Fraud Detection

A real-time transaction fraud detection platform where specialized AI agents — rule-based, statistical, ML, and LLM-driven — collaborate through a shared-state graph to analyze, score, explain, and route financial transactions.

## Why this project is different

Most fraud detection student projects follow the same pattern: load a dataset, train XGBoost, show a confusion matrix, build a dashboard. This system is architecturally different in three ways:

1. **Multi-agent, not single-model.** Eight specialized agents, each responsible for one signal, coordinated via LangGraph instead of one monolithic classifier.
2. **Explainable by construction.** Every decision carries a human-readable reason referencing the specific signal that triggered it — not a post-hoc SHAP plot bolted onto a black box.
3. **Network-aware.** A scheduled Network Intelligence Agent builds a graph from shared devices/addresses across accounts and scores customer-level fraud-ring risk — a signal most single-transaction pipelines never compute.

Everything runs locally, including the LLM (Ollama), so there is no per-request API cost and no transaction data ever leaves the machine.

## Architecture

```
POST /transaction
        │
        ▼
  FastAPI Gateway (auth + validation)
        │
        ▼
  LangGraph Orchestrator (shared state)
        │
        ├─► Ingestion Agent            (enrich with customer/account history)
        ├─► Rule Compliance Agent      (velocity, amount, geo limits)
        ├─► Device Trust Agent         (device reuse / first-seen signals)
        ├─► Behavioral Analysis Agent  (supervised XGBoost on time-gated history features)
        │
        ▼
  Risk Synthesis Agent  (fuses all signals → 0–1 score → allow/flag/block)
        │
        ├─► Explanation Agent   (instant rule-based reason, async LLM reason)
        └─► Case Management Agent  (if flagged/blocked → creates investigation case)
        │
        ▼
  FastAPI Response (decision, score, explanation, case_id)
        │
        ▼
  Streamlit Dashboard (live feed, per-agent status, case queue, analytics)
        │
        ▼
  Investigator resolves case → Feedback stored → retraining trigger
        │
        ▼
  Behavioral Analysis Agent retrained on updated labels

  ── separately, on a schedule (APScheduler) ──
  Network Intelligence Agent → builds device/address graph (networkx)
                              → NetworkRiskScore per customer
```

## Agents

| Agent | Type | Role |
|---|---|---|
| Ingestion | Deterministic | Validates, normalizes, enriches with account history |
| Rule Compliance | Deterministic | Velocity/amount/geo hard limits |
| Behavioral Analysis | ML (XGBoost, supervised) | Per-transaction fraud probability from time-gated customer-history features |
| Device Trust | Statistical | Device reuse, first-seen, age signals |
| Network Intelligence | Graph analytics, async | Shared-device/address graph → ring risk |
| Risk Synthesis | Aggregator | Fuses all signals → unified decision |
| Explanation | Rule-based + local LLM | Instant templated reason + async natural-language reason |
| Case Management | Deterministic | Creates/assigns/tracks investigation cases |

All 8 agents above are core scope (see `docs/DECISIONS.md`, ADR-008). A ninth agent, **Investigator Assistant** (semantic case search via embeddings), is conditional: it is only scheduled after the 8 core agents are complete and demoable, decided at a week-5 checkpoint (ADR-009). A Monitoring Agent was considered and dropped — not part of this project's scope.

## Tech stack

- **Orchestration:** LangGraph
- **API:** FastAPI + Uvicorn, JWT auth via `python-jose` + `passlib` (real auth for Customer/Investigator roles; Admin is a simplified role flag — see ADR-010)
- **ML:** XGBoost (class-weighted, chronological validation), scikit-learn for metrics
- **Graph analytics:** networkx
- **LLM:** Ollama, `llama3.1:8b-instruct` (local, quantized — no API cost, no data leaves the device)
- **Database:** SQLite + SQLAlchemy
- **Scheduling:** APScheduler (Network Intelligence batch job, retraining trigger)
- **Dashboard:** Streamlit + Plotly
- **Testing:** pytest, GitHub Actions CI
- **Package management:** uv
- **Dataset:** [IEEE-CIS Fraud Detection](https://www.kaggle.com/c/ieee-fraud-detection) (Kaggle) — not committed to the repo, see Data below

## Project structure

```
agents/           # 8 agent files + orchestrator.py (LangGraph wiring)
api/               # FastAPI app, entry point, request/response models, JWT auth
  routes/          # route handlers (transaction submission, case endpoints, etc.)
db/                # SQLAlchemy models + session/engine, schema follows the Lab5 ERD
ml/                # train_behavioral.py (XGBoost), evaluation
  artifacts/       # gitignored — trained model files, not committed
dashboard/         # Streamlit app — not yet built
scripts/           # seed_db.py, check_seed.py, prior_txn_buckets.py, feature_signal.py,
                   # replay_eval.py; run_network_batch.py (week 5, not yet built)
tests/             # pytest, mirrors agents/ and api/
  test_agents/
  test_api/
data/              # gitignored except .gitkeep — raw/processed IEEE-CIS data lives here locally
docs/
  DECISIONS.md     # architecture decision log — canonical design-reasoning record;
                    # the actual SE lab submissions are filed separately via MS Teams,
                    # not duplicated in this repo
pyproject.toml
uv.lock
```

Note: `.github/workflows/` (CI) does not exist yet — it's a week-8 addition (see Roadmap), added once there's a test suite worth running on push, not scaffolded early.

## Setup

```bash
# install uv (see astral.sh/uv), then:
git clone <repo-url>
cd 26-27-fall-se-lab-projects-Reddi2802
uv sync
```

Download the IEEE-CIS dataset from Kaggle and place it under `data/raw/` — it is intentionally not committed to this repo (several hundred MB, and license terms don't permit redistribution).

Pull the local LLM:
```bash
ollama pull llama3.1:8b-instruct
```

Run the API:
```bash
uv run uvicorn api.main:app --reload
```

Run the dashboard:
```bash
uv run streamlit run dashboard/app.py
```

Run tests:
```bash
uv run pytest
```

Seed the demo DB (delete fraud_detection.db first if re-seeding):
```bash
uv run python -m scripts.seed_db
uv run python -m scripts.check_seed
```
output must show 0 bad devices.

Train the Behavioral Analysis model (writes `ml/artifacts/`, registers a `ModelVersion` row in the DB):
```bash
uv run python -m ml.train_behavioral
```
After deleting and re-seeding the DB, run it again with `--register-only` to re-register the saved model without retraining.

End-to-end evaluation (replays the seeded customers through the full pipeline against the real fraud labels; reports the held-out period separately):
```bash
uv run python -m scripts.replay_eval
```

## Roadmap

All 8 agents are core scope (ADR-008). Build order is sequenced by dependency and complexity, not by an artificial core/extension split:

- **Week 1:** Ingestion Agent + API Gateway + DB models — foundation everything else builds on.
- **Week 2:** Rule Compliance Agent + Device Trust Agent (both deterministic/statistical, no ML training loop).
- **Week 3:** Behavioral Analysis Agent (supervised XGBoost, ADR-019) — deepest ML component.
- **Week 4:** Risk Synthesis Agent + orchestrator wiring — first end-to-end demo (Ingestion → Rules → Device → Behavioral → decision).
- **Week 5 — checkpoint:** Network Intelligence Agent (graph metrics, async APScheduler job). Go/no-go decision on Investigator Assistant Agent made here against actual progress (ADR-009).
- **Week 6:** Explanation Agent (sync template + async local LLM) + Case Management Agent.
- **Week 7:** Streamlit dashboard, Customer/Investigator JWT auth, Admin role flag, integration testing.
- **Week 8:** Test coverage (pytest), a minimal GitHub Actions CI workflow (run pytest on push), retraining-threshold decision, DECISIONS.md finalization, demo rehearsal.
- **Week 9 (buffer):** Absorbs holiday/lab disruption; Investigator Assistant work lands here if greenlit at the week-5 checkpoint.

## Academic context

This repository is developed for the Software Engineering Laboratory course at VIT Chennai. Design documents (`docs/labs/`) reflect an iterative scope that expanded across lab submissions as new agents were introduced per course requirements — see `docs/DECISIONS.md` for the reasoning behind each addition.
