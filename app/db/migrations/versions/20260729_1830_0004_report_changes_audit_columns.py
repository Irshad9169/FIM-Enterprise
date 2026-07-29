"""audit columns on fim.report_changes

Mirrors fim.alerts.audit_uid/audit_process/audit_command onto the
report-facing fim.report_changes table, so the daily report UI can show
attribution when present, without joining back to fim.alerts. Populated
by report_scheduler.py's _generate_report and app/api/reports.py's
generate_daily_report, both of which build ReportChange rows from Alert
rows.

Revision ID: 0004_report_changes_audit_columns
Revises: 0003_auditd_correlation
Create Date: 2026-07-29 18:30:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = '0004_report_changes_audit_columns'
down_revision: Union[str, None] = '0003_auditd_correlation'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('report_changes', sa.Column('audit_uid', sa.String(length=50), nullable=True), schema='fim')
    op.add_column('report_changes', sa.Column('audit_process', sa.Text(), nullable=True), schema='fim')
    op.add_column('report_changes', sa.Column('audit_command', sa.Text(), nullable=True), schema='fim')


def downgrade() -> None:
    op.drop_column('report_changes', 'audit_command', schema='fim')
    op.drop_column('report_changes', 'audit_process', schema='fim')
    op.drop_column('report_changes', 'audit_uid', schema='fim')
