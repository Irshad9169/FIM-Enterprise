"""content diffing: content_diff column on fim.report_changes

Populated agent-side (agent/fim_agent.py's _diff_content, via a local-only
content shadow copy — never sent to the server, only the resulting unified
diff text is) for changed files matching DETAIL_EXTENSIONS (.conf/.cfg/
.yaml/.yml/.ini/.json). Rides through fim.alerts.current_state (JSONB, no
schema change needed there) and gets extracted into this dedicated column
at report-generation time, same as baseline_hash/current_hash already are.

Revision ID: 0009_report_content_diff
Revises: 0008_agent_api_key_auth
Create Date: 2026-07-30 14:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = '0009_report_content_diff'
down_revision: Union[str, None] = '0008_agent_api_key_auth'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('report_changes', sa.Column('content_diff', sa.Text(), nullable=True), schema='fim')


def downgrade() -> None:
    op.drop_column('report_changes', 'content_diff', schema='fim')
