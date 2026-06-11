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

EOF
