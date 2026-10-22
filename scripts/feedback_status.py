"""
How much investigator feedback has arrived since the current model was trained
(ADR-025).

    uv run python -m scripts.feedback_status

Read-only. It counts Feedback labels submitted after the latest ModelVersion's
trained_at and compares the total with RETRAIN_AFTER_LABELS. It does NOT retrain
and does not feed labels into training: the model trains on the Kaggle CSV labels
(ADR-019), and folding investigator labels in is a stretch item. The threshold
marks when that extension would be worth running.
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import func
from sqlalchemy.orm import Session

from db.models import Feedback, ModelVersion
from db.session import SessionLocal

# ADR-025: a model trained on ~590K labelled rows barely moves for a handful of
# new labels; 100 gives a first batch large enough to evaluate on its own.
RETRAIN_AFTER_LABELS = 100


def feedback_since_last_model(session: Session) -> dict:
    model = (
        session.query(ModelVersion)
        .order_by(ModelVersion.trained_at.desc(), ModelVersion.model_version_id.desc())
        .first()
    )
    query = session.query(Feedback.label, func.count()).group_by(Feedback.label)
    since: datetime | None = model.trained_at if model else None
    if since is not None:
        query = query.filter(Feedback.submitted_at > since)

    counts = {label.value: count for label, count in query}
    total = sum(counts.values())
    return {
        "since": since,
        "fraud": counts.get("fraud", 0),
        "not_fraud": counts.get("not_fraud", 0),
        "total": total,
        "threshold": RETRAIN_AFTER_LABELS,
        "reached": total >= RETRAIN_AFTER_LABELS,
    }


def main() -> None:
    with SessionLocal() as session:
        status = feedback_since_last_model(session)
    since = f"since the model trained at {status['since']:%Y-%m-%d %H:%M} UTC" if status["since"] else "(no model registered yet)"
    print(f"Investigator labels {since}: {status['total']} "
          f"({status['fraud']} fraud, {status['not_fraud']} not fraud); threshold {status['threshold']}.")
    if status["reached"]:
        print("Threshold reached. Feeding these labels into training is not implemented (ADR-025):")
        print("it is the stretch step this threshold is meant to trigger.")
    else:
        print(f"{status['threshold'] - status['total']} more labels until the threshold.")


if __name__ == "__main__":
    main()
