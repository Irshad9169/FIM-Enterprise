"""auditd correlation columns on fim.alerts

Adds audit_uid/audit_process/audit_command — populated agent-side (see
agent/fim_agent.py's _correlate_auditd) via `ausearch` for a curated list
of critical paths (agent_config.yaml's monitoring.audit_critical_paths),
only when that file's content actually changed since the agent's own last
scan. Null for every other file/alert — this is purely additive metadata,
degrades to always-null if auditd isn't installed on a given host.

Re-creates protect_alert_evidence() (from 0002_alert_hash_chain) to also
guard these three new columns — they're part of the detection evidence,
same as everything else that trigger already protects.

Revision ID: 0003_auditd_correlation
Revises: 0002_alert_hash_chain
Create Date: 2026-07-29 18:15:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = '0003_auditd_correlation'
down_revision: Union[str, None] = '0002_alert_hash_chain'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('alerts', sa.Column('audit_uid', sa.String(length=50), nullable=True), schema='fim')
    op.add_column('alerts', sa.Column('audit_process', sa.Text(), nullable=True), schema='fim')
    op.add_column('alerts', sa.Column('audit_command', sa.Text(), nullable=True), schema='fim')

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
                OR NEW.audit_uid IS DISTINCT FROM OLD.audit_uid
                OR NEW.audit_process IS DISTINCT FROM OLD.audit_process
                OR NEW.audit_command IS DISTINCT FROM OLD.audit_command
            THEN
                RAISE EXCEPTION 'fim.alerts detection evidence is immutable (id=%)', OLD.id;
            END IF;

            RETURN NEW;
        END;
        $$ LANGUAGE plpgsql;
    """)


def downgrade() -> None:
    # Restore the 0002 version of the function (without these 3 columns)
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
    op.drop_column('alerts', 'audit_command', schema='fim')
    op.drop_column('alerts', 'audit_process', schema='fim')
    op.drop_column('alerts', 'audit_uid', schema='fim')
