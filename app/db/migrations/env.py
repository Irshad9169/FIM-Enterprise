"""
Alembic environment — async engine variant.

Two things make this different from a stock `alembic init` output:

1. The app uses SQLAlchemy's async engine (asyncpg) everywhere, so
   migrations run through `run_sync()` on an async connection instead of
   a plain sync engine.
2. This schema has years of drift: several tables/columns exist in
   production only via raw SQL in gapNN_*.sh scripts and were never added
   to the SQLAlchemy models (fim.sessions, fim.agent_health_events,
   fim.anomaly_scores, fim.correlation_groups, fim.whitelist_matches,
   fim.rt_ticket_cache — see docs/PRODUCTION_DEPLOYMENT.md and the
   project's schema-reconciliation notes). Autogenerate would otherwise
   see those as "exist in DB, not in metadata" and propose dropping them.
   UNMANAGED_TABLES below tells it to leave those alone.
"""
import asyncio
from logging.config import fileConfig

from sqlalchemy import pool
from sqlalchemy.engine import Connection
from sqlalchemy.ext.asyncio import async_engine_from_config

from alembic import context

from app.core.config import settings
from app.core.database import Base
import app.models  # noqa: F401 — populates Base.metadata as a side effect

config = context.config
config.set_main_option("sqlalchemy.url", settings.database_url)

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = Base.metadata

# Tables that exist in production but are intentionally not modeled in the
# ORM yet — managed via raw SQL elsewhere (session_service.py,
# agent_health.py, anomaly_detector.py, ticket_linker.py, whitelist_checker.py
# etc.). Excluded from autogenerate so it doesn't propose dropping them just
# because Base.metadata doesn't know about them. Adding one of these to a
# real model later automatically takes it out of scope for this filter.
UNMANAGED_TABLES = {
    "sessions",
    "agent_health_events",
    "anomaly_scores",
    "correlation_groups",
    "whitelist_matches",
    # Found via the actual baseline autogenerate diff against production —
    # all pre-existing, real tables with data, just never modeled:
    "file_changes",
    "baseline_history",
    "retention_policies",
    "api_keys",
    "integration_settings",
    "scans_archive",
}

# This app only manages the `fim` schema — ignore anything Alembic finds in
# other schemas (e.g. `public`) rather than risk proposing changes to
# objects (extensions, etc.) this project doesn't own.
MANAGED_SCHEMA = "fim"


def include_name(name, type_, parent_names):
    if type_ == "schema":
        return name in (MANAGED_SCHEMA, None)
    if type_ == "table" and parent_names.get("schema_name") not in (MANAGED_SCHEMA, None):
        return False
    return True


def include_object(object, name, type_, reflected, compare_to):
    if type_ == "table" and reflected and compare_to is None and name in UNMANAGED_TABLES:
        return False
    # Indexes/unique constraints/FKs were never explicitly modeled in the ORM
    # (no Index()/index=True usage anywhere) — modeling every one of them
    # correctly is a separate, much bigger undertaking than this adoption
    # pass. Out of scope for now: Alembic manages tables/columns here, not
    # index or constraint naming/existence.
    if type_ in ("index", "unique_constraint", "foreign_key_constraint"):
        return False
    return True


def run_migrations_offline() -> None:
    """Generate SQL scripts without a live DB connection (`alembic upgrade --sql`)."""
    context.configure(
        url=settings.database_url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        include_schemas=True,
        include_name=include_name,
        include_object=include_object,
        version_table_schema=MANAGED_SCHEMA,
    )
    with context.begin_transaction():
        context.run_migrations()


def do_run_migrations(connection: Connection) -> None:
    # Alembic creates its own bookkeeping table (alembic_version) inside
    # MANAGED_SCHEMA *before* running any migration's upgrade() — including
    # 0000_initial_schema, which is what actually creates that schema. On a
    # genuinely empty database that's a chicken-and-egg failure
    # (InvalidSchemaNameError: schema "fim" does not exist) unless the schema
    # is guaranteed to exist here, first.
    connection.exec_driver_sql(f"CREATE SCHEMA IF NOT EXISTS {MANAGED_SCHEMA}")
    # Commit this as its own unit of work — leaving it open would make it an
    # implicit outer transaction that Alembic's own begin_transaction() below
    # doesn't know about, wrapping every migration as a nested savepoint
    # instead of the real transaction. The outer one then never gets an
    # explicit commit and is silently rolled back on connection close,
    # wiping out everything (confirmed: every "Running upgrade" line logs
    # successfully, but no tables actually persist).
    connection.commit()

    context.configure(
        connection=connection,
        target_metadata=target_metadata,
        include_schemas=True,
        include_name=include_name,
        include_object=include_object,
        version_table_schema=MANAGED_SCHEMA,
    )
    with context.begin_transaction():
        context.run_migrations()


async def run_async_migrations() -> None:
    connectable = async_engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )
    async with connectable.connect() as connection:
        await connection.run_sync(do_run_migrations)
    await connectable.dispose()


def run_migrations_online() -> None:
    asyncio.run(run_async_migrations())


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
