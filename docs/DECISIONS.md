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

### ADR-008 — Core scope is all 8 agents; "Core vs. Extension" tiering retired

**Context:** An earlier internal roadmap (pre-Lab7) split the 8 agents into a "Core" tier (6 agents) and an "Extension" tier (Device Trust, Network Intelligence, treated as optional/later). Lab7's component diagram was then submitted with Device Trust and Network Intelligence fully wired into the orchestrator's coordination and interface contracts (`INetworkRiskScore`).
**Decision:** All 8 agents are core scope. The Core/Extension split is retired as of this ADR. What remains genuinely optional is scoped separately below (ADR-009), not folded into the 8-agent set.
**Why:** A graded, submitted diagram is a commitment. Calling a diagrammed, interface-defined agent "optional" internally creates a document that contradicts the artifact it's supposed to explain — a bad look if a reviewer or interviewer cross-references the repo against the lab submissions.

### ADR-009 — Monitoring Agent cut; Investigator Assistant Agent conditional on a week-5 checkpoint

**Context:** Lab5 explicitly scoped Admin console features (rule config, investigator management, agent-log viewing, drift monitoring) and semantic case search as actor-level capabilities, not standalone system modules to be diagrammed. The README's agent table nonetheless listed a "Monitoring Agent (planned)" and "Investigator Assistant Agent (stretch)" alongside the real 8, which is not what the diagrams committed to.
**Decision:**
- **Monitoring Agent: dropped.** Not built, not diagrammed, not listed as a project agent. Drift monitoring, if mentioned at all, is a "future work" line, not a table entry implying active development.
- **Investigator Assistant Agent (FAISS semantic case search): conditional.** All 8 core agents are built and demonstrable end-to-end first, no exceptions. At the **week-5 checkpoint**, evaluate actual progress against the plan below. Only if the 8-agent pipeline is on track does Investigator Assistant get scheduled into the remaining weeks. This is a scheduled decision point, not an open-ended "if time allows."
**Why:** "If time allows" is how scope drifted before (new agent nearly every lab). A dated checkpoint with a concrete precondition (8 agents done) replaces that pattern with an actual decision rule.

### ADR-010 — RBAC scoped to where it gates real pipeline behavior

**Context:** Admin does not correspond to any of the 8 diagrammed agents — Lab5 treats Admin capabilities (configure rules, manage investigators, view logs) as dashboard-level actor conveniences, not system modules. Customer and Investigator roles, by contrast, gate real pipeline actions: submitting a transaction, reviewing/resolving a fraud case.
**Decision:** Real JWT-based auth (`python-jose` + `passlib`) is implemented for **Customer** and **Investigator** roles, since these gate actual agent-pipeline behavior. **Admin** is implemented as a simplified role flag — sufficient to demo an admin view — without full login/token-verification plumbing behind it.
**Rejected alternative:** Full JWT RBAC across all three roles. Rejected because Admin's capabilities are not exercised by any agent in the pipeline; building real auth infrastructure for a role with no corresponding system logic spends time budget on infrastructure that doesn't demonstrate the project's actual subject matter (multi-agent fraud reasoning), inside a fixed ~8-week build window.

### ADR-011 — Synthetic UID for customer identity (IEEE-CIS has no native key)

UID = card1+addr1+D1, chosen for consensus and simplicity; revisit at week 3 if per-UID transaction-count distribution shows pathological fragmentation or collision.
Observed at seed time: high-count UID collisions are concentrated in rows with missing addr1 and D1=0 — e.g. one UID matched 7,198 rows under this pattern. Confirms the predicted collision risk; the [8,150] seeding range (see scripts/seed_db.py) was chosen specifically to exclude these.

### ADR-012 — Per-UID features must be time-gated, not full-history

**Context:** Behavioral Analysis (ADR-011's UID) needs per-customer aggregate features 
(avg transaction amount, D-column stats, transaction count) to score behavior. Computing 
these from a customer's *entire* transaction history — including transactions after the 
one being scored — leaks future data into the present. This doesn't error out; it just 
produces misleadingly strong validation scores that won't hold up in production, where 
future transactions don't exist yet at scoring time.

**Decision:** Per-UID aggregates are computed only from transactions with an earlier 
`TransactionDT` than the one being scored (expanding window, ordered by time, per UID). 
Train/validation splits for Behavioral Analysis are done by UID, not by row — a UID's 
transactions go entirely into one split, never both.

**Rejected alternative:** Static full-history aggregates per UID. Simpler, but leaks 
future information into past predictions — fine for a one-off Kaggle submission, wrong 
for a system meant to score transactions in real time.

**Consequence:** Feature computation needs a time-ordered expanding aggregation per UID, 
not a single groupby. This matches how a real production system actually works — it never 
has a customer's future transactions when scoring a live one.

### ADR-013 — Seed data sampled from UIDs with 8–150 transactions, not the full population

**Context:** Uniform sampling over all 246,418 UIDs mostly picks thin-history customers (median=1 transaction) — no baseline for Behavioral Analysis (week 3) to learn from. The same distribution's high end is worse: the top UID matched 7,198 rows, concentrated around missing `addr1` + `D1=0` — a card1+addr1+D1 collision merging many different transactions into one UID, not one very active customer.

**Decision:** `scripts/seed_db.py` samples its 1,500 customers only from UIDs with 8–150 transactions. Floor excludes thin-history UIDs; ceiling excludes collision-driven outliers (150 ≈ 1 txn/day sustained over IEEE-CIS's ~6-month window, already generous for a real shopper).

**Rejected alternative:** Uniform sampling (original implementation). Rejected because it's exposed to both problems at once — mostly thin customers, with no protection against collision outliers either.

**Why this isn't a training-data change:** Both bounds are seeding/demo-data policy only. `ml/train_isolation_forest.py` (week 3) trains directly against the unfiltered raw CSV, per ADR-012.
---

## Open items (revisit as the project progresses)

- Retraining trigger threshold (how many new `Feedback` labels before the Behavioral Analysis Agent retrains) — not yet finalized; to be set when the Behavioral Analysis / Case Management feedback loop is built.
- Week-5 checkpoint (ADR-009): go/no-go on Investigator Assistant Agent, decided against actual progress at that point, not in advance.
