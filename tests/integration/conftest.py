"""
Fixtures for integration tests — real HTTP requests against the FastAPI app,
backed by a real (but throwaway) Postgres database.

Schema is created directly from the SQLAlchemy models via
Base.metadata.create_all(), NOT from a pg_dump of any real server. This
project has no from-scratch schema script (see docs/PRODUCTION_DEPLOYMENT.md),
but for testing purposes the ORM models ARE the source of truth for what the
application code actually expects to query — so this is both simpler and more
accurate than depending on a dump from a specific point-in-time production DB.

The DB fixture is function-scoped (fresh schema created and dropped for every
single test) rather than session-scoped. That's slower, but deliberately so:
a session-scoped async fixture needs a session-scoped event loop, which is a
known source of tests hanging indefinitely (rather than failing cleanly) when
mixed with pytest-asyncio's `auto` mode. Function-scoped means every fixture
runs on the same per-test event loop pytest-asyncio already manages by
default — no custom event_loop fixture needed, no loop-mismatch class of bug
possible. Revisit only if test runtime actually becomes a problem.

Requires DATABASE_URL (env var) to point at a real, empty-is-fine Postgres.
In CI this is the `postgres` service container (see .github/workflows/test.yml).
Locally, point it at any throwaway Postgres.
"""
from httpx import AsyncClient, ASGITransport
from sqlalchemy import text

import pytest

from app.core.database import Base, db_manager
import app.models  # noqa: F401 — registers every model on Base.metadata
import app.main as main_module

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


@pytest.fixture
async def _initialized_db():
    await db_manager.initialize()
    async with db_manager.engine.begin() as conn:
        await conn.execute(text("CREATE SCHEMA IF NOT EXISTS fim"))
        await conn.run_sync(Base.metadata.create_all)
        for statement in _SUPPLEMENTARY_DDL.split(";"):
            if statement.strip():
                await conn.execute(text(statement))
    yield
    async with db_manager.engine.begin() as conn:
        await conn.execute(text("DROP SCHEMA IF EXISTS fim CASCADE"))
    await db_manager.close()


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
