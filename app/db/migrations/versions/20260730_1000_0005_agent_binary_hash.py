"""agent self-integrity: binary_hash columns on fim.agents

Trust-on-first-registration: the agent hashes its own running script and
reports it (see agent/fim_agent.py's script_hash field on register/
heartbeat); the server remembers the first hash it ever saw as
"known good" (binary_hash) and records the moment a later report stops
matching (binary_hash_mismatch_since) so it can alert once per new
mismatch rather than every heartbeat. Cleared via
POST /api/v1/agents/{id}/accept-binary-hash after a reviewed, legitimate
agent code update.

Revision ID: 0005_agent_binary_hash
Revises: 0004_report_audit_cols
Create Date: 2026-07-30 10:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = '0005_agent_binary_hash'
down_revision: Union[str, None] = '0004_report_audit_cols'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('agents', sa.Column('binary_hash', sa.String(length=64), nullable=True), schema='fim')
    op.add_column('agents', sa.Column('binary_hash_mismatch_since', sa.DateTime(), nullable=True), schema='fim')
    # Holds the most recently reported (mismatching) hash while a mismatch
    # is pending review — the accept endpoint promotes this to binary_hash.
    # Without this, there'd be nowhere to recover "what the agent actually
    # reported" once the request that triggered the mismatch has finished.
    op.add_column('agents', sa.Column('pending_binary_hash', sa.String(length=64), nullable=True), schema='fim')


def downgrade() -> None:
    op.drop_column('agents', 'pending_binary_hash', schema='fim')
    op.drop_column('agents', 'binary_hash_mismatch_since', schema='fim')
    op.drop_column('agents', 'binary_hash', schema='fim')
