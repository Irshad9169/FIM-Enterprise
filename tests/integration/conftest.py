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


@pytest.fixture(scope="session")
async def _initialized_db():
    await db_manager.initialize()
    async with db_manager.engine.begin() as conn:
        await conn.execute(text("CREATE SCHEMA IF NOT EXISTS fim"))
        await conn.run_sync(Base.metadata.create_all)
    yield
    await db_manager.close()


@pytest.fixture(autouse=True)
async def _clean_tables(_initialized_db):
    """Truncate every table after each test so tests never see each other's data."""
    yield
    table_names = ", ".join(Base.metadata.tables.keys())
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
