# Architecture Decision Log

This log records why this system is built the way it is. The original SE lab submissions (Lab 1–5) are submitted separately via MS Teams and not duplicated here — this file is the standalone record of the reasoning behind the current design, for anyone reading the repo without access to those submissions.

---

### ADR-001 — Pivot from single-model pipeline to multi-agent architecture
**Context:** The initial project brief (Lab 1) proposed a two-stage pipeline — rule engine, then Isolation Forest + XGBoost fused into a risk score. The course instructor approved the fraud-detection concept on the condition that the project incorporate distinct, purpose-built agents, added incrementally.
**Decision:** Rebuilt around a LangGraph-orchestrated multi-agent architecture, where each fraud signal (rules, behavioral anomaly, device trust, network risk) is computed by an independent agent and combined by a Risk Synthesis Agent, rather than one model producing a single score.
**Why this works, not just complies:** A graph-of-agents lets a new agent be added as a new node without rewriting the existing pipeline — which matters directly, since new agents kept being required lab over lab.

### ADR-002 — Device Trust Agent scored statistically, not with ML
**Context:** IEEE-CIS Fraud Detection has device-related columns (`DeviceInfo`, `id_*`) but no ground-truth label for "is this device trustworthy" — training a supervised model here would mean fabricating labels.
**Decision:** Score device trust via explicit signals — device reuse count across distinct customers, first-time-seen flag, device age — rather than a trained model.
**Rejected alternative:** An unsupervised device-anomaly model. Rejected because there's no way to validate it against ground truth, and an unvalidated model is worse than a transparent rule set for an explainability-focused system.

### ADR-003 — Network Intelligence Agent uses classical graph metrics, not a GNN
**Context:** IEEE-CIS has no explicit customer relationship graph. One can be constructed from co-occurrence of shared devices, addresses, or email domains across anonymized accounts.
**Decision:** Build the co-occurrence graph with `networkx`, score customers using degree and clustering-coefficient as fraud-ring signals, computed as an async batch job (APScheduler) rather than per-transaction.
**Rejected alternative:** A graph neural network. Explicitly out of scope — no labeled ring/fraud-network ground truth exists in the dataset, and a GNN adds research-level complexity without a way to validate it, which is a bad trade for a semester project. Classical graph metrics are auditable and explainable, which fits the project's core requirement better than a black-box GNN would.

### ADR-004 — Explanation split into sync rule-based + async local LLM
**Context:** Lab 2's NFR requires a decision within 500ms including the LLM call. On local hardware (RTX 4050, 6GB VRAM) with no paid API budget, a real LLM call realistically takes 1–3 seconds.
**Decision:** Risk Synthesis returns a decision immediately with a fast, templated rule-based explanation (sub-150ms). A richer natural-language explanation generates asynchronously via a local Ollama model and attaches to the record shortly after.
**Why this is a better design, not a workaround:** Real fraud systems don't block a transaction decision on text generation. This also produces a stronger interview talking point than the original spec did.

### ADR-005 — Local LLM (Ollama) instead of a hosted API
**Context:** No budget for paid API usage; hardware supports local quantized inference.
**Decision:** `llama3.1:8b-instruct` via Ollama, run entirely on-device.
**Consequence:** No transaction data ever leaves the machine — a genuine answer to data-privacy questions a fintech-adjacent project should expect in interviews.

### ADR-006 — uv instead of pip/venv
**Decision:** Dependency management via `uv` (`pyproject.toml` + `uv.lock`) rather than `requirements.txt`.
**Why:** Faster installs, reproducible lockfile, single source of truth — avoids the `requirements.txt`/lockfile drift that existed in the repo's earlier (discarded) structure.

### ADR-007 — Commit cadence tied to units of work, not sessions
**Context:** The instructor checks commit history periodically. Early commits were large and infrequent.
**Decision:** One commit per completed agent or feature, mapped to the sprint structure already defined in Lab 3, rather than one commit per working session.

---

## Open items (revisit as the project progresses)
- Retraining trigger threshold (how many new `Feedback` labels before the Behavioral Analysis Agent retrains) — not yet finalized.
- Whether Admin RBAC ships as real JWT auth or a simplified role flag, depending on time remaining in weeks 7–10.
