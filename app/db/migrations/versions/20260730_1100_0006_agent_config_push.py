"""centralized agent config push

Extends the existing heartbeat-response precedent (scan_required already
tells an agent to act now) with the same shape for monitored-path config
changes, instead of inventing a new channel or requiring hand-editing
agent_config.yaml per host (this session fixed a broken agent via manual
sed on one server — this is the alternative to more of that at fleet
scale).

desired_config: admin-pushed {path, exclude_patterns} list (same shape as
agent_config.yaml's monitoring.paths entries).
desired_config_version: bumped on every push.
applied_config_version: last version the agent confirmed applying, via
POST /api/v1/agents/{id}/config/ack.

Revision ID: 0006_agent_config_push
Revises: 0005_agent_binary_hash
Create Date: 2026-07-30 11:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB


revision: str = '0006_agent_config_push'
down_revision: Union[str, None] = '0005_agent_binary_hash'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('agents', sa.Column('desired_config', JSONB(), nullable=True), schema='fim')
    op.add_column(
        'agents',
        sa.Column('desired_config_version', sa.Integer(), nullable=False, server_default='0'),
        schema='fim',
    )
    op.add_column(
        'agents',
        sa.Column('applied_config_version', sa.Integer(), nullable=False, server_default='0'),
        schema='fim',
    )


def downgrade() -> None:
    op.drop_column('agents', 'applied_config_version', schema='fim')
    op.drop_column('agents', 'desired_config_version', schema='fim')
    op.drop_column('agents', 'desired_config', schema='fim')
