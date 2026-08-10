"""system settings: configurable disk warning/critical thresholds

Single-row table for app-wide operator-tunable settings, starting with
the disk usage thresholds that app/api/system.py's disk-health check uses.
These were hardcoded (85/92) after the fim.scans disk-full incident --
making them adjustable via the System Health page instead of a code
change lets an admin tune sensitivity to how full this particular box's
disk normally runs, without needing a redeploy.

Revision ID: 0012_system_settings
Revises: 0011_scans_autovacuum_tuning
Create Date: 2026-08-10 14:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = '0012_system_settings'
down_revision: Union[str, None] = '0011_scans_autovacuum_tuning'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'system_settings',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True, server_default=sa.text('gen_random_uuid()')),
        sa.Column('disk_warning_pct', sa.Numeric(4, 1), nullable=False, server_default='85.0'),
        sa.Column('disk_critical_pct', sa.Numeric(4, 1), nullable=False, server_default='92.0'),
        sa.Column('updated_at', sa.DateTime(), nullable=True),
        sa.Column('updated_by', postgresql.UUID(as_uuid=True), sa.ForeignKey('fim.users.id'), nullable=True),
        schema='fim',
    )
    # Single settings row, always referenced by fixed id -- simpler than a
    # generic key/value table for the handful of tunables this needs so far.
    op.execute("""
        INSERT INTO fim.system_settings (id, disk_warning_pct, disk_critical_pct)
        VALUES ('00000000-0000-0000-0000-000000000001', 85.0, 92.0)
    """)


def downgrade() -> None:
    op.drop_table('system_settings', schema='fim')
