from __future__ import annotations

import os
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

# NOTE: this import is not unused, even though nothing below references
# `models` directly by name. Importing it executes every class body in
# db/models.py, which registers all 14 tables on Base.metadata. Without
# this import, init_db()'s create_all() would run "successfully" but
# silently create zero (or only some) tables. See chat / DECISIONS.md.
import db.models  # noqa: F401
from api.routes import admin, auth, cases, customers, transactions
from db.session import init_db

REPO_ROOT = Path(__file__).resolve().parents[1]
# The website (web/, built with `pnpm build`) is static files served by this same
# process: one server, one origin, no CORS needed in normal use (ADR-027).
WEB_DIR = Path(os.environ.get("WEB_DIR", REPO_ROOT / "web" / "out"))


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    yield


app = FastAPI(title="Multi-Agent Fraud Detection API", lifespan=lifespan)

# Only for the frontend dev loop (`pnpm dev` on :3000 talking to the API on :8000).
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000", "http://127.0.0.1:3000"],
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(auth.router)
app.include_router(transactions.router)
app.include_router(transactions.me_router)
app.include_router(cases.router)
app.include_router(customers.router)
app.include_router(admin.router)


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


# Mounted LAST so every API route above wins over the static catch-all.
if (WEB_DIR / "index.html").exists():
    app.mount("/", StaticFiles(directory=WEB_DIR, html=True), name="web")
else:
    import logging

    logging.getLogger("uvicorn.error").warning(
        "Website not built: %s is missing. Run `cd web && npm install && npm run build`, then restart.",
        WEB_DIR / "index.html",
    )
