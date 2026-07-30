"""agent scan pause/resume + progress reporting

Adds pause/resume control for a running agent scan, surfaced via the
existing heartbeat request/response round-trip (same pattern as
config_version/scan_required). scan_pause_requested is the admin-set
desired state; scan_status/scan_progress_* are reported by the agent
every heartbeat, decoupled from scan completion so the UI shows live
progress even mid-scan. See agent/fim_agent.py's trigger_scan/run_scan
and app/api/agents.py's pause_agent_scan/resume_agent_scan.

Revision ID: 0010_agent_scan_pause
Revises: 0009_report_content_diff
Create Date: 2026-07-30 15:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = '0010_agent_scan_pause'
down_revision: Union[str, None] = '0009_report_content_diff'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('agents', sa.Column('scan_pause_requested', sa.Boolean(), nullable=True, server_default=sa.false()), schema='fim')
    op.add_column('agents', sa.Column('scan_status', sa.String(length=20), nullable=True, server_default='idle'), schema='fim')
    op.add_column('agents', sa.Column('scan_progress_total', sa.Integer(), nullable=True), schema='fim')
    op.add_column('agents', sa.Column('scan_progress_processed', sa.Integer(), nullable=True), schema='fim')
    op.add_column('agents', sa.Column('scan_progress_updated_at', sa.DateTime(), nullable=True), schema='fim')


def downgrade() -> None:
    op.drop_column('agents', 'scan_progress_updated_at', schema='fim')
    op.drop_column('agents', 'scan_progress_processed', schema='fim')
    op.drop_column('agents', 'scan_progress_total', schema='fim')
    op.drop_column('agents', 'scan_status', schema='fim')
    op.drop_column('agents', 'scan_pause_requested', schema='fim')
