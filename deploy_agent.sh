#!/bin/bash
# ══════════════════════════════════════════════════════════════════════════
# FIM Enterprise — Remote Agent Deployment Script
# ══════════════════════════════════════════════════════════════════════════
#
# Deploys the FIM agent to a remote server via SSH.
#
# Usage:
#   /opt/fim/deploy_agent.sh <hostname> [ssh_user]
#   /opt/fim/deploy_agent.sh server01.hyd.int.untd.com
#   /opt/fim/deploy_agent.sh server01.hyd.int.untd.com root
#
# What it does:
#   1. Registers the agent with FIM server (gets agent_id + api_key)
#   2. Copies agent files to remote server
#   3. Generates agent config with correct server URL and credentials
#   4. Creates systemd service
#   5. Starts the agent
#
# Prerequisites:
#   - SSH access to target server (key-based auth recommended)
#   - Python 3.6+ on target server
#   - pip/requests library on target
# ══════════════════════════════════════════════════════════════════════════

set -e

# ── Configuration ─────────────────────────────────────────────────────────
FIM_SERVER_URL="http://$(hostname -f):8000"
FIM_SERVER_DIR="/opt/fim"
AGENT_SOURCE="${FIM_SERVER_DIR}/agent"
API_KEY_FILE="${FIM_SERVER_DIR}/.agent_master_key"

# Colors
RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'; BLUE='\033[0;34m'; NC='\033[0m'
log()  { echo -e "${BLUE}[FIM-Deploy]${NC} $*"; }
ok()   { echo -e "${GREEN}[✓]${NC} $*"; }
warn() { echo -e "${YELLOW}[!]${NC} $*"; }
err()  { echo -e "${RED}[✗]${NC} $*" >&2; }

# ── Parse Arguments ───────────────────────────────────────────────────────
TARGET_HOST="$1"
SSH_USER="${2:-root}"

if [ -z "$TARGET_HOST" ]; then
    echo "Usage: $0 <hostname> [ssh_user]"
    echo ""
    echo "Examples:"
    echo "  $0 server01.hyd.int.untd.com"
    echo "  $0 server01.hyd.int.untd.com root"
    echo "  $0 10.103.32.50 admin"
    echo ""
    echo "Batch deploy:"
    echo "  for h in server0{1..5}.hyd.int.untd.com; do $0 \$h; done"
    exit 1
fi

log "Deploying FIM agent to ${TARGET_HOST} (user: ${SSH_USER})"

# ── Step 1: Test SSH connectivity ─────────────────────────────────────────
log "Testing SSH connection..."
if ! ssh -o ConnectTimeout=5 -o BatchMode=yes "${SSH_USER}@${TARGET_HOST}" "hostname" >/dev/null 2>&1; then
    err "Cannot SSH to ${SSH_USER}@${TARGET_HOST}"
    err "Ensure SSH key-based auth is configured"
    exit 1
fi
ok "SSH connection OK"

# ── Step 2: Get target IP ─────────────────────────────────────────────────
TARGET_IP=$(ssh "${SSH_USER}@${TARGET_HOST}" "hostname -I | awk '{print \$1}'" 2>/dev/null)
TARGET_FQDN=$(ssh "${SSH_USER}@${TARGET_HOST}" "hostname -f" 2>/dev/null)
log "Target: ${TARGET_FQDN} (${TARGET_IP})"

# ── Step 3: Register agent with FIM server ────────────────────────────────
log "Registering agent with FIM server..."

# Get or create API key
if [ -f "$API_KEY_FILE" ]; then
    AGENT_API_KEY=$(cat "$API_KEY_FILE")
else
    AGENT_API_KEY=$(python3 -c "import secrets; print(secrets.token_urlsafe(32))")
    echo "$AGENT_API_KEY" > "$API_KEY_FILE"
    chmod 600 "$API_KEY_FILE"
fi

REGISTER_RESPONSE=$(curl -s -X POST "${FIM_SERVER_URL}/api/v1/agents/register" \
    -H "Content-Type: application/json" \
    -H "X-API-Key: ${AGENT_API_KEY}" \
    -d "{
        \"hostname\": \"${TARGET_FQDN}\",
        \"ip_address\": \"${TARGET_IP}\",
        \"os_type\": \"Linux\",
        \"os_version\": \"$(ssh ${SSH_USER}@${TARGET_HOST} 'cat /etc/redhat-release 2>/dev/null || lsb_release -d 2>/dev/null || echo Linux')\",
        \"agent_version\": \"1.1.0\"
    }" 2>/dev/null)

AGENT_ID=$(echo "$REGISTER_RESPONSE" | python3 -c "import sys,json; print(json.load(sys.stdin).get('agent_id',''))" 2>/dev/null)

if [ -z "$AGENT_ID" ]; then
    warn "Registration response: $REGISTER_RESPONSE"
    warn "Could not extract agent_id — agent may already be registered"
    # Try to find existing agent
    AGENT_ID=$(psql -h localhost -U fim_app -d fim_db -t -A -c \
        "SELECT id FROM fim.agents WHERE hostname = '${TARGET_FQDN}' LIMIT 1" 2>/dev/null | tr -d ' ')
    if [ -z "$AGENT_ID" ]; then
        err "Could not register or find agent"
        exit 1
    fi
    ok "Found existing agent: ${AGENT_ID}"
else
    ok "Agent registered: ${AGENT_ID}"
fi

# ── Step 4: Create remote directories ────────────────────────────────────
log "Creating directories on ${TARGET_HOST}..."
ssh "${SSH_USER}@${TARGET_HOST}" "mkdir -p /opt/fim/agent/config /opt/fim/agent/logs"
ok "Directories created"

# ── Step 5: Copy agent files ──────────────────────────────────────────────
log "Copying agent files..."
scp -q "${AGENT_SOURCE}/fim_agent.py" "${SSH_USER}@${TARGET_HOST}:/opt/fim/agent/fim_agent.py"
ok "Agent script copied"

# ── Step 6: Generate agent config ─────────────────────────────────────────
log "Generating agent config..."
cat > /tmp/fim_agent_config_${TARGET_HOST}.yaml << YAMLEOF
agent:
  id: ${AGENT_ID}
  name: ${TARGET_FQDN}-agent

server:
  url: ${FIM_SERVER_URL}
  api_key: ${AGENT_API_KEY}
  api_version: v1
  timeout: 30
  retry_attempts: 3
  retry_delay: 5

monitoring:
  hash_algorithm: sha256
  scan_time: "02:00"
  heartbeat_interval: 60
  paths:
    - path: /etc
      recursive: true
      exclude_patterns: ['*.tmp', '*.swp', '.git/*']
    - path: /var/www
      recursive: true
      exclude_patterns: ['*.log', 'cache/*']
    - path: /opt
      recursive: true
      exclude_patterns: ['*.pyc', '__pycache__/*', 'fim*']

performance:
  max_workers: 4
  batch_size: 1000
  max_memory: 512

logging:
  level: INFO
  file: /var/log/fim-agent.log
  max_size: 10485760
  backup_count: 5
YAMLEOF

scp -q "/tmp/fim_agent_config_${TARGET_HOST}.yaml" \
    "${SSH_USER}@${TARGET_HOST}:/opt/fim/agent/config/agent_config.yaml"
rm -f "/tmp/fim_agent_config_${TARGET_HOST}.yaml"
ok "Config generated and copied"

# ── Step 7: Install Python dependencies ───────────────────────────────────
log "Installing dependencies..."
ssh "${SSH_USER}@${TARGET_HOST}" "pip3 install requests pyyaml --quiet 2>/dev/null || pip install requests pyyaml --quiet 2>/dev/null || true"
ok "Dependencies installed"

# ── Step 8: Create systemd service ────────────────────────────────────────
log "Creating systemd service..."
ssh "${SSH_USER}@${TARGET_HOST}" "cat > /etc/systemd/system/fim-agent.service << 'SVCEOF'
[Unit]
Description=FIM Enterprise Agent
After=network.target

[Service]
Type=simple
ExecStart=/usr/bin/python3 /opt/fim/agent/fim_agent.py
WorkingDirectory=/opt/fim/agent
Restart=always
RestartSec=10
StandardOutput=journal
StandardError=journal
SyslogIdentifier=fim-agent

[Install]
WantedBy=multi-user.target
SVCEOF
systemctl daemon-reload
systemctl enable fim-agent
systemctl restart fim-agent"

ok "Service created and started"

# ── Step 9: Verify ────────────────────────────────────────────────────────
log "Verifying agent status..."
sleep 3
AGENT_STATUS=$(ssh "${SSH_USER}@${TARGET_HOST}" "systemctl is-active fim-agent" 2>/dev/null)
if [ "$AGENT_STATUS" = "active" ]; then
    ok "Agent is running!"
else
    warn "Agent status: $AGENT_STATUS — check with: ssh ${SSH_USER}@${TARGET_HOST} journalctl -u fim-agent -n 20"
fi

echo ""
echo "═══════════════════════════════════════════════════════════════"
echo "  Deployment Complete"
echo "═══════════════════════════════════════════════════════════════"
echo "  Host     : ${TARGET_FQDN} (${TARGET_IP})"
echo "  Agent ID : ${AGENT_ID}"
echo "  Status   : ${AGENT_STATUS}"
echo "  Config   : /opt/fim/agent/config/agent_config.yaml"
echo "  Logs     : journalctl -u fim-agent -f"
echo "═══════════════════════════════════════════════════════════════"
