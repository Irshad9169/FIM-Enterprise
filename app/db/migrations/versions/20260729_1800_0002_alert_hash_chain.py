"""alert hash chain: tamper-evident fim.alerts

Adds entry_hash/prev_hash to fim.alerts (same chaining pattern already
used on fim.audit_logs) plus a trigger that:
  - blocks DELETE entirely (alerts are append-only; a false positive gets
    marked via status, never removed)
  - blocks UPDATE of the "evidence" columns (agent_id, policy_id,
    alert_type, severity, file_path, previous_state, current_state,
    change_details, detected_at, created_at, is_whitelisted,
    whitelist_rule_id, triggered_by_rule, alert_group_id,
    occurrence_count, entry_hash, prev_hash)

The analyst workflow columns (status, assigned_to, resolution_notes,
acknowledged_at, acknowledged_by, resolved_at) are deliberately NOT
covered — app/api/alert_actions.py updates exactly these on
acknowledge/resolve, and that must keep working.

Revision ID: 0002_alert_hash_chain
Revises: 0001_baseline
Create Date: 2026-07-29 18:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = '0002_alert_hash_chain'
down_revision: Union[str, None] = '0001_baseline'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

GENESIS_HASH = "0" * 64


def upgrade() -> None:
    op.add_column('alerts', sa.Column('entry_hash', sa.String(length=64), nullable=True), schema='fim')
    op.add_column(
        'alerts',
        sa.Column('prev_hash', sa.String(length=64), nullable=True, server_default=GENESIS_HASH),
        schema='fim',
    )

    op.execute("""
        CREATE OR REPLACE FUNCTION fim.protect_alert_evidence() RETURNS TRIGGER AS $$
        BEGIN
            IF TG_OP = 'DELETE' THEN
                RAISE EXCEPTION 'fim.alerts is append-only: DELETE not permitted (id=%)', OLD.id;
            END IF;

            IF NEW.agent_id IS DISTINCT FROM OLD.agent_id
                OR NEW.policy_id IS DISTINCT FROM OLD.policy_id
                OR NEW.alert_type IS DISTINCT FROM OLD.alert_type
                OR NEW.severity IS DISTINCT FROM OLD.severity
                OR NEW.file_path IS DISTINCT FROM OLD.file_path
                OR NEW.previous_state IS DISTINCT FROM OLD.previous_state
                OR NEW.current_state IS DISTINCT FROM OLD.current_state
                OR NEW.change_details IS DISTINCT FROM OLD.change_details
                OR NEW.detected_at IS DISTINCT FROM OLD.detected_at
                OR NEW.created_at IS DISTINCT FROM OLD.created_at
                OR NEW.is_whitelisted IS DISTINCT FROM OLD.is_whitelisted
                OR NEW.whitelist_rule_id IS DISTINCT FROM OLD.whitelist_rule_id
                OR NEW.triggered_by_rule IS DISTINCT FROM OLD.triggered_by_rule
                OR NEW.alert_group_id IS DISTINCT FROM OLD.alert_group_id
                OR NEW.occurrence_count IS DISTINCT FROM OLD.occurrence_count
                OR NEW.entry_hash IS DISTINCT FROM OLD.entry_hash
                OR NEW.prev_hash IS DISTINCT FROM OLD.prev_hash
            THEN
                RAISE EXCEPTION 'fim.alerts detection evidence is immutable (id=%)', OLD.id;
            END IF;

            RETURN NEW;
        END;
        $$ LANGUAGE plpgsql;
    """)

    op.execute("""
        CREATE TRIGGER protect_alert_evidence
            BEFORE UPDATE OR DELETE ON fim.alerts
            FOR EACH ROW EXECUTE FUNCTION fim.protect_alert_evidence();
    """)


def downgrade() -> None:
    op.execute("DROP TRIGGER IF EXISTS protect_alert_evidence ON fim.alerts;")
    op.execute("DROP FUNCTION IF EXISTS fim.protect_alert_evidence();")
    op.drop_column('alerts', 'prev_hash', schema='fim')
    op.drop_column('alerts', 'entry_hash', schema='fim')
