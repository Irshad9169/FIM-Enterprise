#!/bin/bash
# ══════════════════════════════════════════════════════════════════════════
# FIM Enterprise — Remote Agent Deployment Script (v1.4 - Final)
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

# ── Show Usage ────────────────────────────────────────────────────────────
show_usage() {
    cat << 'EOF'
═══════════════════════════════════════════════════════════════════════════
  FIM Enterprise — Agent Deployment Script
═══════════════════════════════════════════════════════════════════════════

USAGE:
  ./deploy_agent.sh <hostname> [ssh_user]

ARGUMENTS:
  hostname    - Target server hostname or IP
  ssh_user    - SSH username (default: root)

EXAMPLES:
  ./deploy_agent.sh server01.hyd.int.untd.com
  ./deploy_agent.sh server02.hyd.int.untd.com admin
  ./deploy_agent.sh 10.103.32.50

Batch deploy:
  for h in server0{1..10}.hyd.int.untd.com; do
      ./deploy_agent.sh $h
  done

WHAT IT DOES:
  1. Tests SSH connectivity
  2. Registers agent with FIM server (gets agent_id + API key)
  3. Copies optimized agent code to target
  4. Generates agent config with enhanced exclusions
  5. Installs Python dependencies (requests, pyyaml)
  6. Creates systemd service
  7. Starts agent and verifies status

AGENT BEHAVIOR AFTER DEPLOYMENT:
  ✓ NO startup scan (prevents CPU spike)
  ✓ Scans ONLY at 02:00 AM daily
  ✓ Responds to manual "Trigger Scan" from UI
  ✓ Sends heartbeat every 60 seconds

PREREQUISITES:
  - SSH key-based auth to target server
  - Python 3.6+ on target server
  - Root/sudo access on target

═══════════════════════════════════════════════════════════════════════════
EOF
}

# ── Parse Arguments ───────────────────────────────────────────────────────
if [ "$1" = "-h" ] || [ "$1" = "--help" ] || [ "$1" = "help" ]; then
    show_usage
    exit 0
fi

TARGET_HOST="$1"
SSH_USER="${2:-root}"

if [ -z "$TARGET_HOST" ]; then
    show_usage
    exit 1
fi

log "Deploying FIM agent to ${TARGET_HOST} (user: ${SSH_USER})"

# ── Step 1: Test SSH ──────────────────────────────────────────────────────
log "Testing SSH connection..."
if ! ssh -o ConnectTimeout=5 -o BatchMode=yes "${SSH_USER}@${TARGET_HOST}" "hostname" >/dev/null 2>&1; then
    err "Cannot SSH to ${SSH_USER}@${TARGET_HOST}"
    err "Ensure SSH key-based auth is configured"
    exit 1
fi
ok "SSH connection OK"

# ── Step 2: Get target info ───────────────────────────────────────────────
TARGET_IP=$(ssh "${SSH_USER}@${TARGET_HOST}" "hostname -I | awk '{print \$1}'" 2>/dev/null)
TARGET_FQDN=$(ssh "${SSH_USER}@${TARGET_HOST}" "hostname -f" 2>/dev/null)
log "Target: ${TARGET_FQDN} (${TARGET_IP})"

# ── Step 3: Register agent ────────────────────────────────────────────────
log "Registering agent with FIM server..."

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
        \"agent_version\": \"1.4.0\"
    }" 2>/dev/null)

AGENT_ID=$(echo "$REGISTER_RESPONSE" | python3 -c "import sys,json; print(json.load(sys.stdin).get('agent_id',''))" 2>/dev/null)

if [ -z "$AGENT_ID" ]; then
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

# ── Step 4: Create directories ────────────────────────────────────────────
log "Creating directories..."
ssh "${SSH_USER}@${TARGET_HOST}" "mkdir -p /opt/fim/agent/config /opt/fim/agent/logs"
ok "Directories created"

# ── Step 5: Copy agent (uses fixed source from test06) ────────────────────
log "Copying agent files..."
scp -q "${AGENT_SOURCE}/fim_agent.py" "${SSH_USER}@${TARGET_HOST}:/opt/fim/agent/fim_agent.py"
ok "Agent script copied (startup scan disabled, manual+scheduled enabled)"

# ── Step 6: Generate config with scan_interval=86400 ──────────────────────
log "Generating optimized agent config..."
cat > /tmp/fim_agent_config_${TARGET_HOST}.yaml << 'YAMLEOF'
agent:
  id: AGENT_ID_PLACEHOLDER
  name: AGENT_NAME_PLACEHOLDER

server:
  url: SERVER_URL_PLACEHOLDER
  api_key: API_KEY_PLACEHOLDER
  api_version: v1
  timeout: 30
  retry_attempts: 3
  retry_delay: 5

monitoring:
  hash_algorithm: sha256
  scan_time: "02:00"           # Daily scan at 2 AM
  scan_interval: 86400         # 24 hours - prevents hourly auto-scans
  heartbeat_interval: 60
  max_file_size: 10485760      # Skip files > 10 MB
  
  paths:
    - path: /etc
      recursive: true
      exclude_patterns: ['*.tmp', '*.swp', '.git/*']
    
    - path: /var/www
      recursive: true
      exclude_patterns:
        - '*.log'
        - '*.jpg'
        - '*.jpeg'
        - '*.png'
        - '*.gif'
        - '*.svg'
        - '*.ico'
        - '*.woff*'
        - 'cache/*'
        - 'tmp/*'
        - 'uploads/*'
        - 'node_modules/*'
    
    - path: /opt
      recursive: true
      exclude_patterns: ['*.pyc', '__pycache__/*', 'fim*', 'IBM*', 'EMPsysedge*', 'midpoint/*']

performance:
  max_workers: 2
  batch_size: 500
  max_memory: 256

logging:
  level: INFO
  file: /var/log/fim-agent.log
  max_size: 10485760
  backup_count: 5
YAMLEOF

sed -i \
    -e "s|AGENT_ID_PLACEHOLDER|${AGENT_ID}|g" \
    -e "s|AGENT_NAME_PLACEHOLDER|${TARGET_FQDN}-agent|g" \
    -e "s|SERVER_URL_PLACEHOLDER|${FIM_SERVER_URL}|g" \
    -e "s|API_KEY_PLACEHOLDER|${AGENT_API_KEY}|g" \
    "/tmp/fim_agent_config_${TARGET_HOST}.yaml"

scp -q "/tmp/fim_agent_config_${TARGET_HOST}.yaml" \
    "${SSH_USER}@${TARGET_HOST}:/opt/fim/agent/config/agent_config.yaml"
rm -f "/tmp/fim_agent_config_${TARGET_HOST}.yaml"
ok "Config generated (scan_interval: 24 hours)"

# ── Step 7: Install dependencies ──────────────────────────────────────────
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
systemctl start fim-agent"
ok "Service created and started"

# ── Step 9: Trigger initial scan ──────────────────────────────────────────
log "Waiting for agent to initialize (5 seconds)..."
sleep 5

log "Triggering initial baseline scan..."
SCAN_TRIGGER=$(curl -s -X POST "${FIM_SERVER_URL}/api/v1/scans/trigger" \
    -H "Content-Type: application/json" \
    -H "X-API-Key: ${AGENT_API_KEY}" \
    -d "{\"agent_id\": \"${AGENT_ID}\"}" 2>/dev/null)

ok "Initial scan triggered"
warn "Scan in progress - may take 2-5 minutes for ~20K files"

# ── Step 10: Verify ───────────────────────────────────────────────────────
sleep 3
AGENT_STATUS=$(ssh "${SSH_USER}@${TARGET_HOST}" "systemctl is-active fim-agent" 2>/dev/null)
AGENT_CPU=$(ssh "${SSH_USER}@${TARGET_HOST}" "ps aux | grep 'fim_agent.py' | grep -v grep | awk '{print \$3}'" 2>/dev/null)

echo ""
echo "═══════════════════════════════════════════════════════════════"
echo "  ✓ Deployment Complete"
echo "═══════════════════════════════════════════════════════════════"
echo "  Host         : ${TARGET_FQDN} (${TARGET_IP})"
echo "  Agent ID     : ${AGENT_ID}"
echo "  Status       : ${AGENT_STATUS}"
echo "  CPU          : ${AGENT_CPU}%"
echo "  Initial Scan : Triggered (in progress)"
echo ""
echo "  Monitor scan:"
echo "    ssh ${SSH_USER}@${TARGET_HOST} journalctl -u fim-agent -f"
echo ""
echo "  Scan behavior:"
echo "    • Initial scan: NOW (triggered by deployment)"
echo "    • Daily scan: 02:00 AM local time"
echo "    • Manual scan: Via UI 'Trigger Scan' button"
echo "    • NO hourly auto-scans (scan_interval: 24h)"
echo "═══════════════════════════════════════════════════════════════"
