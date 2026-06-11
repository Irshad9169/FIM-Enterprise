#!/bin/bash
# ══════════════════════════════════════════════════════════════════════════
# FIM Enterprise — Agent Uninstall Script
# ══════════════════════════════════════════════════════════════════════════

set -e

# Colors
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m'

log()  { echo -e "${BLUE}[FIM-Uninstall]${NC} $*"; }
ok()   { echo -e "${GREEN}[✓]${NC} $*"; }
warn() { echo -e "${YELLOW}[!]${NC} $*"; }
err()  { echo -e "${RED}[✗]${NC} $*" >&2; }

# ── Show Usage ────────────────────────────────────────────────────────────
show_usage() {
    cat << 'EOF'
═══════════════════════════════════════════════════════════════════════════
  FIM Enterprise — Agent Uninstall Script
═══════════════════════════════════════════════════════════════════════════

USAGE:
  ./uninstall_agent.sh <hostname> [ssh_user] [remove_from_db]

ARGUMENTS:
  hostname         - Target server hostname or IP
  ssh_user         - SSH username (default: root)
  remove_from_db   - Remove from database? yes/no (default: no)

EXAMPLES:
  
  1. Uninstall agent only (keeps in database, shows as 'offline'):
     ./uninstall_agent.sh server01.hyd.int.untd.com
     ./uninstall_agent.sh 10.103.32.50
  
  2. Uninstall agent with custom SSH user:
     ./uninstall_agent.sh server01.hyd.int.untd.com admin
  
  3. Uninstall agent AND remove from database:
     ./uninstall_agent.sh server01.hyd.int.untd.com root yes
     ./uninstall_agent.sh server02.hyd.int.untd.com root yes
  
  4. Batch uninstall multiple agents:
     for h in server0{1..5}.hyd.int.untd.com; do
         ./uninstall_agent.sh $h root yes
     done
  
  5. Uninstall all agents in a subnet:
     for i in {10..20}; do
         ./uninstall_agent.sh 10.103.32.$i root yes
     done

WHAT IT DOES:
  1. Stops the fim-agent systemd service
  2. Disables the service (prevents auto-start)
  3. Removes /etc/systemd/system/fim-agent.service
  4. Deletes /opt/fim/agent directory
  5. Deletes /opt/fim-agent directory
  6. Removes /var/log/fim-agent.log*
  7. (Optional) Removes agent record from database

NOTE:
  - If 'remove_from_db' is 'no' (default), agent will show as 'offline'
    in the dashboard but data is preserved for historical reference
  
  - If 'remove_from_db' is 'yes', agent is marked inactive (audit trail preserved) including:
    * All associated baselines
    * All associated scans
    * All associated alerts
    * Audit logs remain intact

PREREQUISITES:
  - SSH key-based authentication to target server
  - Root or sudo access on target server
  - Database access if removing from DB (runs on FIM server)

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
REMOVE_FROM_DB="${3:-no}"

if [ -z "$TARGET_HOST" ]; then
    show_usage
    exit 1
fi

# Validate remove_from_db argument
if [ "$REMOVE_FROM_DB" != "yes" ] && [ "$REMOVE_FROM_DB" != "no" ]; then
    err "Invalid argument: remove_from_db must be 'yes' or 'no'"
    echo ""
    echo "Usage: $0 <hostname> [ssh_user] [yes|no]"
    exit 1
fi

echo ""
log "Uninstalling FIM agent from ${TARGET_HOST}"
log "SSH User: ${SSH_USER}"
log "Remove from DB: ${REMOVE_FROM_DB}"
echo ""

# ── Step 1: Test SSH connectivity ─────────────────────────────────────────
log "Testing SSH connection..."
if ! ssh -o ConnectTimeout=5 "${SSH_USER}@${TARGET_HOST}" "hostname" >/dev/null 2>&1; then
    err "Cannot SSH to ${SSH_USER}@${TARGET_HOST}"
    err "Ensure SSH key-based auth is configured"
    exit 1
fi
ok "SSH connection OK"

# ── Step 2: Get agent info ────────────────────────────────────────────────
TARGET_FQDN=$(ssh "${SSH_USER}@${TARGET_HOST}" "hostname -f" 2>/dev/null)
log "Target: ${TARGET_FQDN}"

# ── Step 3: Check if agent is installed ───────────────────────────────────
log "Checking if agent is installed..."
AGENT_EXISTS=$(ssh "${SSH_USER}@${TARGET_HOST}" "[ -d /opt/fim/agent ] && echo yes || echo no" 2>/dev/null)

if [ "$AGENT_EXISTS" = "no" ]; then
    warn "No agent installation found on ${TARGET_FQDN}"
    
    if [ "$REMOVE_FROM_DB" = "yes" ]; then
        log "Checking database for orphaned records..."
        AGENT_ID=$(psql -h localhost -U fim_app -d fim_db -t -A -c \
            "SELECT id FROM fim.agents WHERE hostname = '${TARGET_FQDN}' LIMIT 1" 2>/dev/null | tr -d ' ')
        
        if [ ! -z "$AGENT_ID" ]; then
                psql -h localhost -U fim_app -d fim_db -c \
                    "UPDATE fim.agents SET status = 'inactive' WHERE id = '${AGENT_ID}';" >/dev/null 2>&1
            ok "Marked agent inactive in database (ID: ${AGENT_ID})"
        else
            ok "No database record found either"
        fi
    fi
    
    echo ""
    echo "═══════════════════════════════════════════════════════════════"
    echo "  ✓ Nothing to uninstall"
    echo "═══════════════════════════════════════════════════════════════"
    echo "  Host: ${TARGET_FQDN}"
    echo "  Status: No agent found"
    echo "═══════════════════════════════════════════════════════════════"
    exit 0
fi

ok "Agent installation found"

# ── Step 4: Stop and disable service ──────────────────────────────────────
log "Stopping FIM agent service..."
ssh "${SSH_USER}@${TARGET_HOST}" "
    systemctl stop fim-agent 2>/dev/null || true
    systemctl disable fim-agent 2>/dev/null || true
    rm -f /etc/systemd/system/fim-agent.service
    systemctl daemon-reload
    systemctl reset-failed fim-agent 2>/dev/null || true
"
ok "Service stopped and disabled"

# ── Step 5: Kill any running processes ────────────────────────────────────
log "Killing any remaining agent processes..."
ssh "${SSH_USER}@${TARGET_HOST}" "pkill -9 -f fim_agent.py 2>/dev/null || true"
ok "Processes killed"

# ── Step 6: Remove agent files ────────────────────────────────────────────
log "Removing agent files..."
ssh "${SSH_USER}@${TARGET_HOST}" "
    rm -rf /opt/fim/agent
    rm -rf /opt/fim-agent
    rm -f /var/log/fim-agent.log*
    
    # Remove parent directory if empty
    rmdir /opt/fim 2>/dev/null || true
"
ok "Agent files removed"

# ── Step 7: Remove from database (optional) ───────────────────────────────
if [ "$REMOVE_FROM_DB" = "yes" ]; then
    log "Removing agent from database..."
    
    AGENT_ID=$(psql -h localhost -U fim_app -d fim_db -t -A -c \
        "SELECT id FROM fim.agents WHERE hostname = '${TARGET_FQDN}' LIMIT 1" 2>/dev/null | tr -d ' ')
    
    if [ ! -z "$AGENT_ID" ]; then
        # Get counts before deletion
        BASELINE_COUNT=$(psql -h localhost -U fim_app -d fim_db -t -A -c \
            "SELECT COUNT(*) FROM fim.baselines WHERE agent_id = '${AGENT_ID}';" 2>/dev/null)
        SCAN_COUNT=$(psql -h localhost -U fim_app -d fim_db -t -A -c \
            "SELECT COUNT(*) FROM fim.scans WHERE agent_id = '${AGENT_ID}';" 2>/dev/null)
        ALERT_COUNT=$(psql -h localhost -U fim_app -d fim_db -t -A -c \
            "SELECT COUNT(*) FROM fim.alerts WHERE agent_id = '${AGENT_ID}';" 2>/dev/null)
        
        # Mark agent inactive (audit trail preserved — scans, alerts, baselines kept)
            psql -h localhost -U fim_app -d fim_db -c \
                "UPDATE fim.agents SET status = 'inactive' WHERE id = '${AGENT_ID}';" >/dev/null 2>&1
        
        ok "Agent marked inactive in database (audit trail preserved)"
        echo "  → Preserved: ${BASELINE_COUNT} baselines, ${SCAN_COUNT} scans, ${ALERT_COUNT} alerts (audit trail intact)"
    else
        warn "Agent not found in database"
    fi
else
    warn "Agent NOT removed from database (will show as 'offline' in dashboard)"
    echo "  → To remove from DB, run: $0 ${TARGET_HOST} ${SSH_USER} yes"
fi

# ── Step 8: Verify ────────────────────────────────────────────────────────
log "Verifying uninstall..."

# Check for processes
AGENT_RUNNING=$(ssh "${SSH_USER}@${TARGET_HOST}" "ps aux | grep fim_agent | grep -v grep" 2>/dev/null || true)
if [ -z "$AGENT_RUNNING" ]; then
    ok "No agent processes found"
else
    warn "Agent process still running (shouldn't happen):"
    echo "$AGENT_RUNNING"
fi

# Check for files
AGENT_FILES=$(ssh "${SSH_USER}@${TARGET_HOST}" "ls -d /opt/fim/agent /opt/fim-agent 2>/dev/null" || true)
if [ -z "$AGENT_FILES" ]; then
    ok "No agent files found"
else
    warn "Some files still remain:"
    echo "$AGENT_FILES"
fi

echo ""
echo "═══════════════════════════════════════════════════════════════"
echo "  ✓ Uninstall Complete"
echo "═══════════════════════════════════════════════════════════════"
echo "  Host       : ${TARGET_FQDN}"
echo "  Files      : Removed"
echo "  Service    : Removed"
echo "  Database   : $([ "$REMOVE_FROM_DB" = "yes" ] && echo "Marked inactive" || echo "Not removed (offline)")"
echo "═══════════════════════════════════════════════════════════════"
