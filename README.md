# Multi-Agent AI System for Real-Time Financial Fraud Detection

**Author:** Hridhayansh Reddi Bommana (24BDS1028)
**Course:** Software Engineering Laboratory, VIT Chennai

## Problem

Rule-based fraud detection systems are rigid, adapt poorly to new fraud patterns,
and generate high false-positive rates that overload investigation teams. This
project builds a real-time transaction monitoring platform that combines
rule-based checks with machine-learning anomaly detection, splits the decision
process across specialized AI agents, and routes flagged transactions to
investigators through an automated case management workflow.

## Architecture

The system is split into two tiers:

**Synchronous pipeline** (runs per-transaction, inside the latency budget):

1. **Transaction Ingestion Agent** — validates, normalizes, and enriches the
   incoming transaction with account history.
2. **Behavioural Analysis Agent** — scores the transaction against a
   per-customer Isolation Forest baseline.
3. **Device Trust Agent** — scores device/session signals against the
   customer's device history.
4. **Rule Compliance Agent** — checks hard business/regulatory limits
   (velocity, amount, geography).
5. **Risk Synthesis Agent** — combines all upstream signals (including the
   precomputed network-risk score below) into a single 0–1 risk score and an
   allow/flag/block decision.
6. **Explanation Agent** — generates a plain-language justification for the
   decision, referencing only signals the other agents actually detected.
7. **Case Management Agent** — auto-creates and assigns an investigation case
   for blocked transactions.

**Asynchronous job** (runs on a schedule, outside the per-transaction path):

8. **Network Intelligence Agent** — builds a co-occurrence graph across
   card/address/device identifiers to detect coordinated fraud across
   customers and merchants, and writes a per-customer network-risk score that
   Risk Synthesis reads at inference time. This runs as a batch job rather
   than inline because graph construction can't fit inside a per-transaction
   latency budget.

```
Transaction
    │
    ▼
FastAPI Gateway (auth + validation)
    │
    ▼
LangGraph Orchestrator (shared state)
    │
    ▼
Transaction Ingestion
    │
    ├──► Behavioural Analysis ─┐
    ├──► Device Trust          ├──► Risk Synthesis ──► Explanation + Case Management
    └──► Rule Compliance ──────┘         ▲
                                          │
                          Network Intelligence (async batch job)
```

Investigator decisions on cases are stored as labelled data and periodically
used to retrain the Behavioural Analysis Agent.

## Tech Stack

| Layer | Technology |
|---|---|
| Orchestration | LangGraph |
| API | FastAPI + Uvicorn |
| ML | scikit-learn (Isolation Forest), XGBoost, imbalanced-learn |
| Explanation LLM | Local (Ollama / llama3) or OpenAI (gpt-4o-mini) |
| Database | SQLite + SQLAlchemy |
| Dashboard | Streamlit + Plotly |
| Testing | pytest |
| Dataset | [IEEE-CIS Fraud Detection](https://www.kaggle.com/c/ieee-fraud-detection) (Kaggle) |

## Non-Functional Requirements

- **Latency:** ≤500ms per transaction decision, including the explanation step.
- **Throughput:** ≥500 transactions/minute without degradation.
- **Accuracy:** ≤5% false positive rate on the IEEE-CIS held-out test set.
- **Explainability:** every flagged/blocked transaction includes a
  human-readable explanation citing at least one detected signal.
- **Reliability:** pipeline logs and continues on individual agent failure
  rather than dropping the transaction.
- **Maintainability:** each agent is independently testable and replaceable
  without changing the orchestration layer.

## Project Structure

```
.
├── app/
│   ├── agents/            # One module per agent (7 synchronous + 1 async)
│   ├── orchestration/      # LangGraph pipeline wiring
│   ├── api/                # FastAPI app and routes
│   ├── db/                 # SQLAlchemy models and session setup
│   ├── core/                # Shared config/utilities
│   └── models/              # Trained ML model artifacts
├── dashboard/               # Streamlit monitoring dashboard
├── scripts/                 # Batch jobs (e.g. network graph construction)
├── data/                    # raw/ and processed/ datasets (gitignored)
├── tests/                   # pytest test suite
├── docs/                    # Architecture notes, ER diagram
└── .github/workflows/       # CI pipeline
```

## Getting Started

```bash
# clone and set up
git clone <this-repo-url>
cd fraud-detection-repo
python -m venv venv && source venv/bin/activate
pip install -r requirements.txt

# run the API
uvicorn app.api.main:app --reload

# run the dashboard
streamlit run dashboard/app.py
```

## Status

Architecture and repo structure defined. Agent implementations are pending —
see `docs/architecture.md` for detailed per-agent design notes (to be added).

## Agile Process

Developed using Scrum, with each agent built, unit-tested, and integrated
independently before the next is started. See `docs/architecture.md` for the
sprint breakdown.
