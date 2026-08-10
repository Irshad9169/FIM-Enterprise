#!/bin/bash

export PGPASSFILE=/opt/fim/.pgpass

psql -h localhost -U fim_app -d fim_db <<'EOF'

UPDATE fim.scans
SET scan_data = NULL
WHERE ctid IN (
    SELECT ctid
    FROM fim.scans
    WHERE created_at < NOW() - INTERVAL '30 days'
      AND scan_data IS NOT NULL
    LIMIT 100
);

-- Scans are operational telemetry, not the tamper-evident audit trail
-- (that's fim.alerts) -- nothing depends on a scan row surviving past its
-- usefulness, so past 3 months the whole row goes, not just its payload.
-- scan_requests.scan_id references this via ON DELETE SET NULL, so an old
-- scan_request just loses its pointer rather than blocking the delete.
DELETE FROM fim.scans
WHERE ctid IN (
    SELECT ctid
    FROM fim.scans
    WHERE created_at < NOW() - INTERVAL '3 months'
    LIMIT 500
);

-- Nulling scan_data only marks the old TOASTed value dead -- it doesn't
-- reclaim disk space by itself. Without this, every run of this script
-- silently grows the table's on-disk size forever, never shrinking it.
-- Found live: fim.scans hit 15GB with only 15 rows and scan_data NULL
-- on all of them, because this script had been "cleaning up" for months
-- with no VACUUM ever following it.
VACUUM fim.scans;

EOF
