#!/bin/bash
# ══════════════════════════════════════════════════════════════════════════
# FIM Enterprise — Remote Agent Deployment Script (v1.3)
# With initial scan support
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
SKIP_INITIAL_SCAN="${3:-no}"  # yes/no - skip initial scan

if [ -z "$TARGET_HOST" ]; then
    cat << 'EOF'
Usage: ./deploy_agent.sh <hostname> [ssh_user] [skip_initial_scan]

Examples:
  ./deploy_agent.sh server01.hyd.int.untd.com               # Deploy with initial scan
  ./deploy_agent.sh server01.hyd.int.untd.com root yes      # Deploy WITHOUT initial scan
  ./deploy_agent.sh 10.103.32.50 admin                      # Custom user

Batch deploy:
  for h in server0{1..5}.hyd.int.untd.com; do ./deploy_agent.sh $h; done
EOF
    exit 1
fi

log "Deploying FIM agent to ${TARGET_HOST} (user: ${SSH_USER})"
log "Initial scan: $([ "$SKIP_INITIAL_SCAN" = "yes" ] && echo "DISABLED" || echo "ENABLED")"

# ── Step 1-3: SSH test, get info, register agent (same as before) ─────────
log "Testing SSH connection..."
if ! ssh -o ConnectTimeout=5 -o BatchMode=yes "${SSH_USER}@${TARGET_HOST}" "hostname" >/dev/null 2>&1; then
    err "Cannot SSH to ${SSH_USER}@${TARGET_HOST}"
    exit 1
fi
ok "SSH connection OK"

TARGET_IP=$(ssh "${SSH_USER}@${TARGET_HOST}" "hostname -I | awk '{print \$1}'" 2>/dev/null)
TARGET_FQDN=$(ssh "${SSH_USER}@${TARGET_HOST}" "hostname -f" 2>/dev/null)
log "Target: ${TARGET_FQDN} (${TARGET_IP})"

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
        \"os_version\": \"$(ssh ${SSH_USER}@${TARGET_HOST} 'cat /etc/redhat-release 2>/dev/null || echo Linux')\",
        \"agent_version\": \"1.3.0\"
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

# ── Step 5: Prepare agent code (SMART scan control) ───────────────────────
log "Preparing agent code..."
TEMP_AGENT="/tmp/fim_agent_${TARGET_HOST}.py"
cp "${AGENT_SOURCE}/fim_agent.py" "$TEMP_AGENT"

# Comment out ONLY the hourly scan_interval check
# Keep initial scan and manual trigger working
sed -i.orig \
    -e '/# Scheduled scan/,/last_scan = time.time()/s/\([[:space:]]*\)self\.run_scan()/\1# self.run_scan()  # Disabled: use scan_time instead/' \
    "$TEMP_AGENT"

ok "Agent code prepared"

# ── Step 6: Copy agent ────────────────────────────────────────────────────
log "Copying agent files..."
scp -q "$TEMP_AGENT" "${SSH_USER}@${TARGET_HOST}:/opt/fim/agent/fim_agent.py"
rm -f "$TEMP_AGENT" "${TEMP_AGENT}.orig"
ok "Agent script copied"

# ── Step 7: Generate config ───────────────────────────────────────────────
log "Generating agent config..."
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
  heartbeat_interval: 60
  max_file_size: 10485760
  
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
ok "Config generated"

# ── Step 8: Install dependencies ──────────────────────────────────────────
log "Installing dependencies..."
ssh "${SSH_USER}@${TARGET_HOST}" "pip3 install requests pyyaml --quiet 2>/dev/null || true"
ok "Dependencies installed"

# ── Step 9: Create systemd service ────────────────────────────────────────
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
systemctl enable fim-agent"
ok "Service created"

# ── Step 10: Start agent (with or without initial scan) ───────────────────
if [ "$SKIP_INITIAL_SCAN" = "yes" ]; then
    log "Starting agent (NO initial scan)..."
    ssh "${SSH_USER}@${TARGET_HOST}" "systemctl start fim-agent"
    ok "Agent started (waiting for 02:00 or manual trigger)"
else
    log "Starting agent with INITIAL SCAN..."
    ssh "${SSH_USER}@${TARGET_HOST}" "
        # Start agent
        systemctl start fim-agent
        
        # Wait for agent to initialize
        sleep 5
        
        # Trigger initial scan via API
        curl -s -X POST '${FIM_SERVER_URL}/api/v1/scans/trigger' \
            -H 'Content-Type: application/json' \
            -H 'X-API-Key: ${AGENT_API_KEY}' \
            -d '{\"agent_id\": \"${AGENT_ID}\"}' >/dev/null 2>&1 || true
    "
    ok "Agent started with initial scan triggered"
    warn "Initial scan in progress - may take 2-5 minutes depending on file count"
fi

# ── Step 11: Verify ───────────────────────────────────────────────────────
sleep 3
AGENT_STATUS=$(ssh "${SSH_USER}@${TARGET_HOST}" "systemctl is-active fim-agent" 2>/dev/null)
AGENT_CPU=$(ssh "${SSH_USER}@${TARGET_HOST}" "ps aux | grep 'fim_agent.py' | grep -v grep | awk '{print \$3}'" 2>/dev/null)

echo ""
echo "═══════════════════════════════════════════════════════════════"
echo "  ✓ Deployment Complete"
echo "═══════════════════════════════════════════════════════════════"
echo "  Host        : ${TARGET_FQDN} (${TARGET_IP})"
echo "  Agent ID    : ${AGENT_ID}"
echo "  Status      : ${AGENT_STATUS}"
echo "  CPU         : ${AGENT_CPU}%"
echo "  Initial Scan: $([ "$SKIP_INITIAL_SCAN" = "yes" ] && echo "Skipped (waits for 02:00)" || echo "Triggered")"
echo ""
echo "  Monitor: ssh ${SSH_USER}@${TARGET_HOST} journalctl -u fim-agent -f"
echo "  Dashboard: Check agent appears online in UI"
echo "═══════════════════════════════════════════════════════════════"
