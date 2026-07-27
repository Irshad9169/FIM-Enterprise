"""
Fixtures for integration tests — real HTTP requests against the FastAPI app,
backed by a real (but throwaway) Postgres database.

Schema is created directly from the SQLAlchemy models via
Base.metadata.create_all(), NOT from a pg_dump of any real server. This
project has no from-scratch schema script (see docs/PRODUCTION_DEPLOYMENT.md),
but for testing purposes the ORM models ARE the source of truth for what the
application code actually expects to query — so this is both simpler and more
accurate than depending on a dump from a specific point-in-time production DB.

Requires DATABASE_URL (env var) to point at a real, empty-is-fine Postgres.
In CI this is the `postgres` service container (see .github/workflows/test.yml).
Locally, point it at any throwaway Postgres — never a real database with real
data, since tables get truncated between every test.
"""
import asyncio

from httpx import AsyncClient, ASGITransport
from sqlalchemy import text

import pytest

from app.core.database import Base, db_manager
import app.models  # noqa: F401 — registers every model on Base.metadata
import app.main as main_module


@pytest.fixture(scope="session")
def event_loop():
    """
    Session-scoped event loop so the session-scoped _initialized_db fixture
    below (and the asyncpg connection pool it creates) is used from a single
    consistent loop across every test in the run — mixing a session-scoped
    async resource with pytest-asyncio's default per-function loop raises
    "attached to a different loop" errors otherwise.
    """
    loop = asyncio.get_event_loop_policy().new_event_loop()
    yield loop
    loop.close()


# The ORM models in app/models/models.py have drifted from the real schema —
# some tables and columns exist only via raw SQL (text()) elsewhere in the
# app and were never added to the SQLAlchemy models. `fim.sessions` is one
# such table (used by app/services/session_service.py, hit on every login
# and every authenticated request via get_current_user's session-revocation
# check), and `fim.users` is missing last_login/last_login_ip for the same
# reason. This supplements Base.metadata.create_all() with exactly what's
# needed for the current test suite to run — NOT a claim that this is the
# complete real schema. Other tables in the same situation
# (agent_health_events, anomaly_scores, correlation_groups, whitelist_matches)
# aren't included here because nothing in the current tests touches them;
# add them here if a future test needs one.
_SUPPLEMENTARY_DDL = """
CREATE EXTENSION IF NOT EXISTS pgcrypto;

ALTER TABLE fim.users ADD COLUMN IF NOT EXISTS last_login TIMESTAMP;
ALTER TABLE fim.users ADD COLUMN IF NOT EXISTS last_login_ip VARCHAR(50);

CREATE TABLE IF NOT EXISTS fim.sessions (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id UUID NOT NULL REFERENCES fim.users(id) ON DELETE CASCADE,
    token_jti VARCHAR(64) NOT NULL,
    ip_address VARCHAR(50),
    user_agent TEXT,
    created_at TIMESTAMP DEFAULT NOW(),
    last_activity TIMESTAMP DEFAULT NOW(),
    expires_at TIMESTAMP NOT NULL,
    is_revoked BOOLEAN DEFAULT false,
    revoked_at TIMESTAMP,
    revoked_by UUID
);
"""

# Tables that exist only via the DDL above, not via any SQLAlchemy model —
# Base.metadata doesn't know about these, so they need to be truncated
# separately from the ORM-registered tables.
_SUPPLEMENTARY_TABLES = ["fim.sessions"]


@pytest.fixture(scope="session")
async def _initialized_db():
    await db_manager.initialize()
    async with db_manager.engine.begin() as conn:
        await conn.execute(text("CREATE SCHEMA IF NOT EXISTS fim"))
        await conn.run_sync(Base.metadata.create_all)
        for statement in _SUPPLEMENTARY_DDL.split(";"):
            if statement.strip():
                await conn.execute(text(statement))
    yield
    await db_manager.close()


@pytest.fixture(autouse=True)
async def _clean_tables(_initialized_db):
    """Truncate every table after each test so tests never see each other's data."""
    yield
    table_names = ", ".join(list(Base.metadata.tables.keys()) + _SUPPLEMENTARY_TABLES)
    async with db_manager.engine.begin() as conn:
        await conn.execute(text(f"TRUNCATE TABLE {table_names} RESTART IDENTITY CASCADE"))


@pytest.fixture
async def db_session(_initialized_db):
    session = db_manager.get_session()
    try:
        yield session
    finally:
        await session.close()


@pytest.fixture
async def client(_initialized_db):
    transport = ASGITransport(app=main_module.app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as ac:
        yield ac
