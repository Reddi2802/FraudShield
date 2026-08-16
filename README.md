# Multi-Agent AI System for Real-Time Financial Fraud Detection

A real-time transaction fraud detection platform where specialized AI agents — rule-based, statistical, ML, and LLM-driven — collaborate through a shared-state graph to analyze, score, explain, and route financial transactions. Built for the VIT Chennai Software Engineering Lab (24BDS1028), and doubling as a portfolio project.

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
        ├─► Behavioral Analysis Agent  (per-customer Isolation Forest)
        ├─► Device Trust Agent         (device reuse / first-seen signals)
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
| Behavioral Analysis | ML (Isolation Forest) | Per-customer anomaly scoring |
| Device Trust | Statistical | Device reuse, first-seen, age signals |
| Network Intelligence | Graph analytics, async | Shared-device/address graph → ring risk |
| Risk Synthesis | Aggregator | Fuses all signals → unified decision |
| Explanation | Rule-based + local LLM | Instant templated reason + async natural-language reason |
| Case Management | Deterministic | Creates/assigns/tracks investigation cases |
| Monitoring *(planned)* | Statistical | Watches prediction drift, flags retraining need |
| Investigator Assistant *(stretch)* | Semantic search | Finds similar past cases via embeddings |

## Tech stack

- **Orchestration:** LangGraph
- **API:** FastAPI + Uvicorn, JWT auth via `python-jose` + `passlib` (customer/investigator/admin roles)
- **ML:** scikit-learn (Isolation Forest), XGBoost, imbalanced-learn (SMOTE)
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
agents/           # all 8 agents + orchestrator.py (LangGraph wiring)
api/               # FastAPI app, routes, auth
db/                # SQLAlchemy models + session
ml/                # training scripts, evaluation, gitignored model artifacts
dashboard/         # Streamlit app
scripts/           # seed_db.py, run_network_batch.py, etc.
tests/             # pytest, mirrors agents/ and api/
docs/
  labs/            # the 5 SE lab submissions this project is graded against
  DECISIONS.md     # architecture decision log
data/              # gitignored — raw/processed IEEE-CIS data lives here locally
.github/workflows/ # CI
pyproject.toml
uv.lock
```

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

## Roadmap

- **Weeks 1–6 (Core):** Ingestion, Rule Compliance, Behavioral Analysis, Risk Synthesis, Explanation, Case Management — end-to-end pipeline, evaluated on precision/recall/F1/FPR.
- **Weeks 7–10 (Extension):** Device Trust, Network Intelligence, RBAC/Admin console, investigator feedback → retraining loop, Monitoring Agent.
- **Weeks 11–12 (Stretch):** Investigator Assistant (semantic case search), CI, decision log polish.

## Academic context

This repository is developed for the Software Engineering Laboratory course at VIT Chennai. Design documents (`docs/labs/`) reflect an iterative scope that expanded across lab submissions as new agents were introduced per course requirements — see `docs/DECISIONS.md` for the reasoning behind each addition.
