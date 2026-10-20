from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import FastAPI

# NOTE: this import is not unused, even though nothing below references
# `models` directly by name. Importing it executes every class body in
# db/models.py, which registers all 14 tables on Base.metadata. Without
# this import, init_db()'s create_all() would run "successfully" but
# silently create zero (or only some) tables. See chat / DECISIONS.md.
import db.models  # noqa: F401
from api.routes import auth, cases, transactions
from db.session import init_db


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    yield


app = FastAPI(title="Multi-Agent Fraud Detection API", lifespan=lifespan)

app.include_router(auth.router)
app.include_router(transactions.router)
app.include_router(transactions.me_router)
app.include_router(cases.router)


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}
