#!/bin/bash
# ══════════════════════════════════════════════════════════════════
# backup_fim.sh — FIM Enterprise complete backup
# Run:  bash /opt/fim/backup_fim.sh
# Cron: 0 2 * * * bash /opt/fim/backup_fim.sh >> /var/log/backup-fim.log 2>&1
# ══════════════════════════════════════════════════════════════════
set -euo pipefail

BACKUP_DIR="/opt/fim/backup/fim"
DATE=$(date +%Y%m%d_%H%M)
LOG="/var/log/backup-fim.log"
KEEP_DAYS=7
DB_USER="fim_app"
DB_PASS="FIM_Secure_Pass_2025!"
DB_NAME="fim_db"

log() { echo "[$(date '+%Y-%m-%d %H:%M:%S')] $*" | tee -a "$LOG"; }

log "══════════════════════════════════════════════"
log "FIM Enterprise Backup Started — $DATE"
log "══════════════════════════════════════════════"

mkdir -p "$BACKUP_DIR"

# ── 1. Database ───────────────────────────────────────────────────
log "[1/5] Database backup..."
if PGPASSWORD="$DB_PASS" pg_dump \
    -h localhost -U "$DB_USER" "$DB_NAME" 2>/dev/null | \
    gzip > "$BACKUP_DIR/fim_db_${DATE}.sql.gz"; then
    SIZE=$(du -sh "$BACKUP_DIR/fim_db_${DATE}.sql.gz" | cut -f1)
    log "      OK  fim_db_${DATE}.sql.gz  ($SIZE)"
else
    log "      ERROR: FIM database backup failed"
    exit 1
fi

# ── 2. Code ───────────────────────────────────────────────────────
log "[2/5] Code backup..."
cd /opt
zip -qr "$BACKUP_DIR/fim_code_${DATE}.zip" fim/ \
    --exclude "fim/.venv/*" \
    --exclude "fim/node_modules/*" \
    --exclude "fim/app/node_modules/*" \
    --exclude "fim/agent/node_modules/*" \
    --exclude "fim/__pycache__/*" \
    --exclude "fim/app/__pycache__/*" \
    --exclude "fim/.env" \
    --exclude "fim/backups/*" \
    --exclude "fim/fim-backups/*"
SIZE=$(du -sh "$BACKUP_DIR/fim_code_${DATE}.zip" | cut -f1)
log "      OK  fim_code_${DATE}.zip  ($SIZE)"

# ── 3. Secrets & configs ──────────────────────────────────────────
log "[3/5] Secrets and configs..."
mkdir -p /tmp/fim_cfg_${DATE}

cp /opt/fim/.env /tmp/fim_cfg_${DATE}/fim.env 2>/dev/null || true

# FIM config files
[ -d /opt/fim/config ] && \
    cp /opt/fim/config/* /tmp/fim_cfg_${DATE}/ 2>/dev/null || true

# systemd service files
cp /etc/systemd/system/fim-*.service /tmp/fim_cfg_${DATE}/ 2>/dev/null || true

# nginx config
cp /etc/nginx/conf.d/fim*.conf /tmp/fim_cfg_${DATE}/ 2>/dev/null || true

# email map and exclusions
cp /opt/fim/email_map.conf            /tmp/fim_cfg_${DATE}/ 2>/dev/null || true
cp /opt/fim/fim-global-exclusions.txt /tmp/fim_cfg_${DATE}/ 2>/dev/null || true

zip -qj "$BACKUP_DIR/fim_configs_${DATE}.zip" \
    /tmp/fim_cfg_${DATE}/*
chmod 600 "$BACKUP_DIR/fim_configs_${DATE}.zip"
rm -rf /tmp/fim_cfg_${DATE}
log "      OK  fim_configs_${DATE}.zip  (permissions: 600)"

# ── 4. Agent packages ─────────────────────────────────────────────
log "[4/5] Agent packages..."
if [ -d /opt/fim/agent ]; then
    cd /opt/fim
    zip -qr "$BACKUP_DIR/fim_agents_${DATE}.zip" agent/ \
        --exclude "agent/node_modules/*" \
        --exclude "agent/__pycache__/*"
    SIZE=$(du -sh "$BACKUP_DIR/fim_agents_${DATE}.zip" | cut -f1)
    log "      OK  fim_agents_${DATE}.zip  ($SIZE)"
else
    log "      SKIP: No agent directory found"
fi

# ── 5. Cleanup ────────────────────────────────────────────────────
log "[5/5] Cleaning backups older than ${KEEP_DAYS} days..."
find "$BACKUP_DIR" -name "fim_*" -mtime +${KEEP_DAYS} -delete
REMAINING=$(ls "$BACKUP_DIR"/fim_* 2>/dev/null | wc -l)
log "      Remaining backup files: $REMAINING"

# ── Summary ───────────────────────────────────────────────────────
log ""
log "══ FIM Backup Summary ═══════════════════════"
ls -lh "$BACKUP_DIR"/fim_*${DATE}* 2>/dev/null | \
    awk '{print "  " $5 "\t" $9}' | tee -a "$LOG"
TOTAL=$(du -sh "$BACKUP_DIR" | cut -f1)
log "Backup dir total size: $TOTAL"
log "FIM backup DONE — $DATE"
log ""
