"""fix agent authentication bypass: real per-agent api_key_hash

Confirmed via full codebase research that /register, /heartbeat, and
/scans/submit had no real server-side credential check at all —
scans.py's HMAC "verification" computed the expected signature using the
X-API-Key header of the SAME incoming request (self-consistency, not
authentication); register/heartbeat checked nothing. See
app/core/agent_auth.py for the fix: trust-on-first-contact, same pattern
already used for Agent.binary_hash.

Revision ID: 0008_agent_api_key_auth
Revises: 0007_agent_reported_config
Create Date: 2026-07-30 13:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = '0008_agent_api_key_auth'
down_revision: Union[str, None] = '0007_agent_reported_config'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('agents', sa.Column('api_key_hash', sa.String(length=64), nullable=True), schema='fim')


def downgrade() -> None:
    op.drop_column('agents', 'api_key_hash', schema='fim')
