"""agent-reported current config (fixes blank config editor)

The config-push editor (GET /api/v1/agents/{id}/config) only ever showed
desired_config — what's been PUSHED via the new fleet-config feature —
which is null for every pre-existing agent, since nothing's been pushed
yet. There was no way to see what an agent is ACTUALLY monitoring right
now (that only lives in its local agent_config.yaml). Opening the editor
for an already-configured agent showed a blank form instead of its real
paths.

reported_config: what the agent says it's currently running (sent on
both register and heartbeat, mirrors self.scanner.path_configs — always
kept fresh, not trust-on-first-sight like binary_hash). Purely for
display/pre-fill; does not participate in the push/apply/ack protocol at
all — desired_config remains the only thing that actually changes what
an agent monitors.

Revision ID: 0007_agent_reported_config
Revises: 0006_agent_config_push
Create Date: 2026-07-30 12:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB


revision: str = '0007_agent_reported_config'
down_revision: Union[str, None] = '0006_agent_config_push'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('agents', sa.Column('reported_config', JSONB(), nullable=True), schema='fim')


def downgrade() -> None:
    op.drop_column('agents', 'reported_config', schema='fim')
