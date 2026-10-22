# Multi-Agent AI System for Real-Time Financial Fraud Detection

A real-time transaction fraud detection platform where specialized AI agents — rule-based, statistical, ML, and LLM-driven — collaborate through a shared-state graph to analyze, score, explain, and route financial transactions.

## Why this project is different

Most fraud detection student projects follow the same pattern: load a dataset, train XGBoost, show a confusion matrix, build a dashboard. This system is architecturally different in three ways:

1. **Multi-agent, not single-model.** Eight specialized agents, each responsible for one signal, coordinated via LangGraph instead of one monolithic classifier.
2. **Explainable by construction.** Every decision carries a human-readable reason referencing the specific signal that triggered it — not a post-hoc SHAP plot bolted onto a black box.
3. **Network-aware.** A Network Intelligence Agent builds a graph from devices shared across accounts and scores customer-level fraud-ring risk — a signal most single-transaction pipelines never compute.

Everything runs locally (SQLite, a local XGBoost model, no paid APIs), so there is no per-request API cost and no transaction data ever leaves the machine. A local LLM (Ollama) for richer explanations is a planned stretch item.

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
        ├─► Rule Compliance Agent      (velocity and amount limits)
        ├─► Device Trust Agent         (device reuse / first-seen signals)
        ├─► Behavioral Analysis Agent  (supervised XGBoost on time-gated history features)
        │
        ▼
  Risk Synthesis Agent  (fuses all signals → 0–1 score → allow/flag/block)
        │
        ├─► Explanation Agent   (plain-language reason + technical evidence; LLM enrichment is a stretch item)
        └─► Case Management Agent  (if flagged/blocked → creates investigation case)
        │
        ▼
  FastAPI Response (decision, score, explanation, case_id)
        │
        ▼
  Streamlit Dashboard (submit page, case queue, admin overview)
        │
        ▼
  Investigator resolves case → Feedback stored → manual retraining script (automatic trigger = stretch)
        │
        ▼
  Behavioral Analysis Agent retrained on updated labels

  ── separately, as a batch job (manual script; scheduling is a stretch item) ──
  Network Intelligence Agent → builds shared-device graph (networkx)
                              → NetworkRiskScore per customer
```

## Agents

| Agent | Type | Role |
|---|---|---|
| Ingestion | Deterministic | Validates, normalizes, enriches with account history |
| Rule Compliance | Deterministic | Velocity and amount hard limits |
| Behavioral Analysis | ML (XGBoost, supervised) | Per-transaction fraud probability from time-gated customer-history features |
| Device Trust | Statistical | Device reuse, first-seen, age signals |
| Network Intelligence | Graph analytics (batch script) | Shared-device graph → ring risk |
| Risk Synthesis | Aggregator | Fuses all signals → unified decision |
| Explanation | Deterministic template (LLM = stretch) | Plain-language reason plus technical evidence |
| Case Management | Deterministic | Opens a case per flagged/blocked transaction; stores investigator feedback |

All 8 agents above are core scope (see `docs/DECISIONS.md`, ADR-008). A ninth agent, **Investigator Assistant** (semantic case search via embeddings), is conditional: it is only scheduled after the 8 core agents are complete and demoable, decided at a week-5 checkpoint (ADR-009). A Monitoring Agent was considered and dropped — not part of this project's scope.

## Tech stack

- **Orchestration:** LangGraph
- **API:** FastAPI + Uvicorn, JWT auth via `python-jose` + `passlib` (real auth for Customer/Investigator roles; Admin is a simplified role flag — see ADR-010)
- **ML:** XGBoost (class-weighted, chronological validation), scikit-learn for metrics
- **Graph analytics:** networkx
- **LLM (stretch):** Ollama, `llama3.1:8b-instruct` (local, quantized — no API cost, no data leaves the device) for richer explanations
- **Database:** SQLite + SQLAlchemy
- **Scheduling (stretch):** APScheduler for the Network Intelligence batch job and retraining trigger; until then both run as manual scripts
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
dashboard/         # Streamlit app: Submit transaction (customer), Case queue (investigator),
                   # Admin overview (demo flag)
scripts/           # seed_db.py, check_seed.py, prior_txn_buckets.py, feature_signal.py,
                   # replay_eval.py, fusion_check.py, seed_investigators.py, demo_auth_flow.py,
                   # run_network_batch.py, feedback_status.py
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

CI: `.github/workflows/ci.yml` runs the test suite on every push and pull request to `main`.

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

Run the dashboard (from the repo root, with the API running in another terminal; `API_URL` overrides the default `http://127.0.0.1:8000`):
```bash
uv run streamlit run dashboard/app.py
```
Log in from the sidebar with a demo account (password `ChangeMe123!`): `seed.customer.00001@example.invalid` as `customer`, or `investigator1@example.invalid` as `investigator`. The sidebar checkbox **Admin view (demo flag)** shows a read-only overview.

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

Create the two demo investigators (idempotent; password `ChangeMe123!`, the same demo password as every seeded customer):
```bash
uv run python -m scripts.seed_investigators
```
Log in with `POST /auth/login` (`{email, password, role}`). Seeded customers: `seed.customer.00001@example.invalid`, role `customer`. Investigators: `investigator1@example.invalid`, role `investigator`. Set the `JWT_SECRET` environment variable for anything beyond a local demo (a development default is used, with a warning, when it is missing).

See the whole flow (login, submit, flagged case, investigator review, feedback) with the server running in another terminal:
```bash
uv run python -m scripts.demo_auth_flow
```

Train the Behavioral Analysis model (writes `ml/artifacts/`, registers a `ModelVersion` row in the DB):
```bash
uv run python -m ml.train_behavioral
```
After deleting and re-seeding the DB, run it again with `--register-only` to re-register the saved model without retraining.

End-to-end evaluation (replays the seeded customers through the full pipeline against the real fraud labels; reports the held-out period separately):
```bash
uv run python -m scripts.replay_eval
# after the replay finishes: test fusion weights offline in seconds
uv run python -m scripts.fusion_check
```

Network Intelligence batch job (run after seeding and whenever device links change; Risk Synthesis reads the latest scores):
```bash
uv run python -m scripts.run_network_batch
```

How much investigator feedback has arrived since the model was trained (ADR-025):
```bash
uv run python -m scripts.feedback_status
```

## Roadmap

All 8 agents are core scope (ADR-008). Build order is sequenced by dependency and complexity, not by an artificial core/extension split:

- **Week 1:** Ingestion Agent + API Gateway + DB models — foundation everything else builds on.
- **Week 2:** Rule Compliance Agent + Device Trust Agent (both deterministic/statistical, no ML training loop).
- **Week 3:** Behavioral Analysis Agent (supervised XGBoost, ADR-019) — deepest ML component.
- **Week 4:** Risk Synthesis Agent + orchestrator wiring — first end-to-end demo (Ingestion → Rules → Device → Behavioral → decision).
- **Week 5 — checkpoint:** Network Intelligence Agent (graph metrics; manual batch script, scheduler is a stretch item). Go/no-go decision on Investigator Assistant Agent made here against actual progress (ADR-009).
- **Week 6:** Explanation Agent (deterministic template; LLM enrichment is a stretch item) + Case Management Agent.
- **Week 7:** Streamlit dashboard, Customer/Investigator JWT auth, Admin role flag, integration testing.
- **Week 8:** Test coverage (pytest), a minimal GitHub Actions CI workflow (run pytest on push), retraining-threshold decision, DECISIONS.md finalization, demo rehearsal.
- **Week 9 (buffer):** Absorbs holiday/lab disruption; Investigator Assistant work lands here if greenlit at the week-5 checkpoint.

## Academic context

This repository is developed for the Software Engineering Laboratory course at VIT Chennai. Design documents (`docs/labs/`) reflect an iterative scope that expanded across lab submissions as new agents were introduced per course requirements — see `docs/DECISIONS.md` for the reasoning behind each addition.
