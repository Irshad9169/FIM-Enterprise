#!/bin/bash
# Update agent status based on last_heartbeat age

psql -h localhost -U fim_app -d fim_db <<SQL
-- Mark agents as offline if heartbeat > 10 minutes old
UPDATE fim.agents 
SET status = 'offline', is_healthy = false
WHERE status = 'online' 
  AND last_heartbeat < NOW() - INTERVAL '10 minutes';

-- Mark agents as online if heartbeat is recent
UPDATE fim.agents 
SET status = 'online', is_healthy = true
WHERE status = 'offline' 
  AND last_heartbeat >= NOW() - INTERVAL '10 minutes';
SQL

echo "✅ Agent statuses updated at $(date)"
