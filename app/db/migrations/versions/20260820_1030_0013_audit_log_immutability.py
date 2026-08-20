"""audit log immutability: block DELETE/UPDATE on fim.audit_logs

scripts/gap10_audit_log_protection.sh already creates this trigger by hand
against real deployments, but it was never captured as a migration —
meaning a fresh install (or a new instance that hasn't had gap10 run
against it yet) silently has a mutable audit log. DDL below is copied
unchanged from that script's "Layer 1: Database triggers" section.

Revision ID: 0013_audit_log_immutability
Revises: 0012_system_settings
Create Date: 2026-08-20 10:30:00.000000

"""
from typing import Sequence, Union

from alembic import op


revision: str = '0013_audit_log_immutability'
down_revision: Union[str, None] = '0012_system_settings'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("""
        CREATE OR REPLACE FUNCTION fim.raise_audit_immutable()
        RETURNS TRIGGER AS $$
        BEGIN
            RAISE EXCEPTION
                'SECURITY: fim.audit_logs is immutable. '
                '% operation is not permitted. Session user: %',
                TG_OP, SESSION_USER;
            RETURN NULL;
        END;
        $$ LANGUAGE plpgsql SECURITY DEFINER;
    """)

    op.execute("DROP TRIGGER IF EXISTS prevent_audit_delete ON fim.audit_logs;")
    op.execute("DROP TRIGGER IF EXISTS prevent_audit_update ON fim.audit_logs;")

    op.execute("""
        CREATE TRIGGER prevent_audit_delete
            BEFORE DELETE ON fim.audit_logs
            FOR EACH ROW EXECUTE FUNCTION fim.raise_audit_immutable();
    """)

    op.execute("""
        CREATE TRIGGER prevent_audit_update
            BEFORE UPDATE ON fim.audit_logs
            FOR EACH ROW EXECUTE FUNCTION fim.raise_audit_immutable();
    """)


def downgrade() -> None:
    op.execute("DROP TRIGGER IF EXISTS prevent_audit_delete ON fim.audit_logs;")
    op.execute("DROP TRIGGER IF EXISTS prevent_audit_update ON fim.audit_logs;")
    op.execute("DROP FUNCTION IF EXISTS fim.raise_audit_immutable();")
