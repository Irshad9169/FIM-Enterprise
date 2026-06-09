#!/bin/bash
# 1. Push Master Configs to all online agents
AGENTS=$(psql -h localhost -U fim_app -d fim_db -t -c "SELECT hostname FROM fim.agents WHERE status='online';")

echo "--- Starting Golden Run: $(date) ---"

for HOST in $AGENTS; do
    if [ -f "/opt/fim/master_configs/$HOST.yaml" ]; then
        echo "Pushing tamper-proof config to $HOST..."
        scp /opt/fim/master_configs/$HOST.yaml root@$HOST:/opt/fim/agent/config/agent_config.yaml
    fi
    # Optional: Trigger an immediate scan on the agent if you want the report 
    # to include the very latest state.
    # ssh root@$HOST "systemctl restart fim-agent"
done

# 2. Generate the report via API (This triggers the Delta logic and JIT Correlation)
# We use the admin account to perform this system action
TOKEN=$(curl -s -X POST http://localhost:8000/api/v1/auth/login \
  -H "Content-Type: application/json" \
  -d '{"username":"admin","password":"admin123"}' | jq -r '.access_token')

curl -X POST http://localhost:8000/api/v1/reports/generate \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d "{}"

echo "--- Golden Run Complete ---"
