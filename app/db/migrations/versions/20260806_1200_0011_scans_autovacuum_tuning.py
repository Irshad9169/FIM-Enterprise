"""tune autovacuum thresholds on fim.scans

fim.scans stores each scan's full file listing in scan_data (JSONB) --
tens of thousands of files per submission, so individual values are huge
and TOASTed. cleanup_scan_data.sh nulls out scan_data for rows older than
30 days, but an UPDATE only marks the old TOASTed value dead; it doesn't
reclaim space. Default autovacuum triggers off live/dead *row* counts,
which stay tiny on this table (a handful of scan rows) regardless of how
bloated the TOAST storage gets -- so autovacuum essentially never fires
here on its own. Found live: fim.scans reached 15GB on disk with only 15
live rows and scan_data NULL on all of them, which filled the disk and
took down the whole app (Postgres couldn't even write its own init file).

Lowering the scale factor to 0 and the threshold to a small fixed count
makes autovacuum trigger on this table after a handful of dead tuples,
independent of table size -- a safety net that doesn't depend on
cleanup_scan_data.sh (or anything else) running correctly.

Revision ID: 0011_scans_autovacuum_tuning
Revises: 0010_agent_scan_pause
Create Date: 2026-08-06 12:00:00.000000

"""
from typing import Sequence, Union

from alembic import op


revision: str = '0011_scans_autovacuum_tuning'
down_revision: Union[str, None] = '0010_agent_scan_pause'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("""
        ALTER TABLE fim.scans SET (
            autovacuum_vacuum_scale_factor = 0.0,
            autovacuum_vacuum_threshold = 20,
            autovacuum_analyze_scale_factor = 0.0,
            autovacuum_analyze_threshold = 20
        );
    """)


def downgrade() -> None:
    op.execute("""
        ALTER TABLE fim.scans RESET (
            autovacuum_vacuum_scale_factor,
            autovacuum_vacuum_threshold,
            autovacuum_analyze_scale_factor,
            autovacuum_analyze_threshold
        );
    """)
