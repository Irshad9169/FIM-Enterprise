#!/bin/bash
# 1. Get current list of agents
AGENTS=$(psql -h localhost -U fim_app -d fim_db -t -c "SELECT hostname FROM fim.agents WHERE status='online';")

# 2. Define the Report Date (Today)
REPORT_DATE=$(date '+%Y-%m-%d')

echo "--- Starting Golden Scan for $REPORT_DATE ---"

for HOST in $AGENTS; do
    # A. Push Master Config (Tamper-proofing)
    if [ -f "/opt/fim/master_configs/$HOST.yaml" ]; then
        scp /opt/fim/master_configs/$HOST.yaml root@$HOST:/opt/fim/agent/config/agent_config.yaml
    fi

    # B. Trigger Daily Scan
    # The --daily flag tells the agent to do a deep scan and upload immediately
    ssh root@$HOST "cd /opt/fim/agent && /usr/local/opt/fim/venv/bin/python3 fim_agent.py --daily"
done

# 3. Trigger Report Generation via API
# This will perform the correlation logic for the alerts found in the last 24h
TOKEN=$(curl -s -X POST http://localhost:8000/api/v1/auth/login \
  -H "Content-Type: application/json" \
  -d '{"username":"admin","password":"admin123"}' | jq -r '.access_token')

curl -X POST http://localhost:8000/api/v1/reports/generate \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d "{\"report_date\": \"$REPORT_DATE\"}"

echo "--- Golden Run Complete ---"
