#!/bin/bash
# Master Daily Integrity Control
# 1. Overwrite agent configs from central storage
# 2. Trigger a Full Daily Scan

# Get list of agents from DB
AGENTS=$(psql -h localhost -U fim_app -d fim_db -t -c "SELECT hostname FROM fim.agents WHERE status='online';")

for HOST in $AGENTS; do
    echo "------------------------------------------------"
    echo "🚀 Starting Daily Integrity Run for: $HOST"
    
    # 1. Push Tamper-Proof Config
    # Assumes you have a folder /opt/fim/master_configs/HOST.yaml
    if [ -f "/opt/fim/master_configs/$HOST.yaml" ]; then
        scp /opt/fim/master_configs/$HOST.yaml root@$HOST:/opt/fim/agent/config/agent_config.yaml
        echo "✅ Config Overwritten (Tamper-Proofing complete)"
    fi

    # 2. Trigger the Daily Scan via SSH 
    # (Using the specific --daily flag we will add to the agent)
    ssh root@$HOST "cd /opt/fim/agent && ./venv/bin/python3 fim_agent.py --config config/agent_config.yaml --daily"
    echo "✅ Daily Scan Initiated for $HOST"
done
