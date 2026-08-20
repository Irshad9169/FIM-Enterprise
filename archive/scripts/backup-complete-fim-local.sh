#!/bin/bash
#
# backup_fim.sh — FIM Enterprise Complete Backup
#
# Usage:  /opt/fim/backup_fim.sh
# Cron:   0 2 * * * /opt/fim/backup_fim.sh >> /var/log/backup-fim.log 2>&1
#
# Requirements:
#   - /opt/fim/.pgpass must exist and be chmod 600
#     Format:  localhost:5432:fim_db:fim_app:<password>
#   - pg_dump, zip must be installed
#

set -euo pipefail

##############################################################################
# Configuration
##############################################################################

DATE=$(date +%Y%m%d_%H%M%S)
BACKUP_DIR="/backup/fim"
TMP_DIR="/tmp/fim_backup_${DATE}"
LOG_FILE="/var/log/backup-fim.log"
KEEP_DAYS=10

DB_HOST="localhost"
DB_PORT="5432"
DB_NAME="fim_db"
DB_USER="fim_app"

# Use .pgpass for authentication — never hardcode passwords.
# File must be:  chmod 600 /opt/fim/.pgpass
export PGPASSFILE="/opt/fim/.pgpass"

##############################################################################
# Functions
##############################################################################

log() {
    echo "[$(date '+%F %T')] $*" | tee -a "$LOG_FILE"
}

die() {
    log "ERROR: $*"
    exit 1
}

cleanup() {
    rm -rf "$TMP_DIR" >/dev/null 2>&1 || true
}

trap cleanup EXIT

##############################################################################
# Pre-flight checks
##############################################################################

[[ -f "$PGPASSFILE" ]] || die ".pgpass not found at $PGPASSFILE"
[[ -z "$(find "$PGPASSFILE" -perm 600 2>/dev/null)" ]] && die "$PGPASSFILE must be chmod 600"
command -v pg_dump >/dev/null 2>&1 || die "pg_dump not found"
command -v zip     >/dev/null 2>&1 || die "zip not found"

mkdir -p "$BACKUP_DIR"
mkdir -p "$TMP_DIR"

log "======================================================"
log "FIM Enterprise Backup Started"
log "Timestamp : ${DATE}"
log "Backup dir: ${BACKUP_DIR}"
log "======================================================"

##############################################################################
# 1. PostgreSQL — Full Database (Custom Format)
##############################################################################

log "[1/6] Backing up PostgreSQL database (full)..."

pg_dump \
    -h "$DB_HOST" \
    -p "$DB_PORT" \
    -U "$DB_USER" \
    -Fc \
    "$DB_NAME" \
    -f "$BACKUP_DIR/fim_db_${DATE}.dump" \
    || die "pg_dump (full) failed"

SIZE=$(du -sh "$BACKUP_DIR/fim_db_${DATE}.dump" | awk '{print $1}')
log "      OK  fim_db_${DATE}.dump (${SIZE})"

##############################################################################
# 2. PostgreSQL — Schema Only
##############################################################################

log "[2/6] Backing up PostgreSQL schema..."

pg_dump \
    -h "$DB_HOST" \
    -p "$DB_PORT" \
    -U "$DB_USER" \
    -Fc \
    -s \
    "$DB_NAME" \
    -f "$BACKUP_DIR/fim_schema_${DATE}.dump" \
    || die "pg_dump (schema) failed"

SIZE=$(du -sh "$BACKUP_DIR/fim_schema_${DATE}.dump" | awk '{print $1}')
log "      OK  fim_schema_${DATE}.dump (${SIZE})"

##############################################################################
# 3. Application Code
##############################################################################

log "[3/6] Backing up application code..."

cd /opt

zip -qr \
    "$BACKUP_DIR/fim_code_${DATE}.zip" \
    fim/ \
    -x "fim/.venv/*" \
    -x "fim/node_modules/*" \
    -x "fim/app/node_modules/*" \
    -x "fim/agent/node_modules/*" \
    -x "fim/__pycache__/*" \
    -x "fim/app/__pycache__/*" \
    -x "fim/agent/__pycache__/*" \
    -x "fim/.git/*" \
    -x "fim/backup/*" \
    -x "fim/backups/*" \
    -x "fim/fim-backups/*" \
    -x "fim/frontend/dist/*" \
    || die "Code zip failed"

SIZE=$(du -sh "$BACKUP_DIR/fim_code_${DATE}.zip" | awk '{print $1}')
log "      OK  fim_code_${DATE}.zip (${SIZE})"

##############################################################################
# 4. Configurations and Secrets
##############################################################################

log "[4/6] Backing up configurations..."

mkdir -p "$TMP_DIR/configs"

# Application configs
cp -a /opt/fim/.env                    "$TMP_DIR/configs/"       2>/dev/null || true
cp -a /opt/fim/config                  "$TMP_DIR/configs/"       2>/dev/null || true
cp -a /opt/fim/email_map.conf          "$TMP_DIR/configs/"       2>/dev/null || true
cp -a /opt/fim/fim-global-exclusions.txt "$TMP_DIR/configs/"     2>/dev/null || true

# Systemd service files
cp -a /etc/systemd/system/fim-*.service "$TMP_DIR/configs/"      2>/dev/null || true

# Nginx
cp -a /etc/nginx/conf.d/fim*.conf      "$TMP_DIR/configs/"       2>/dev/null || true

# PostgreSQL configs
cp -a /var/lib/pgsql/15/data/postgresql.conf "$TMP_DIR/configs/" 2>/dev/null || true
cp -a /var/lib/pgsql/15/data/pg_hba.conf     "$TMP_DIR/configs/" 2>/dev/null || true
cp -a /var/lib/pgsql/15/data/pg_ident.conf   "$TMP_DIR/configs/" 2>/dev/null || true

cd "$TMP_DIR"
zip -qr \
    "$BACKUP_DIR/fim_configs_${DATE}.zip" \
    configs/ \
    || die "Config zip failed"

chmod 600 "$BACKUP_DIR/fim_configs_${DATE}.zip"

SIZE=$(du -sh "$BACKUP_DIR/fim_configs_${DATE}.zip" | awk '{print $1}')
log "      OK  fim_configs_${DATE}.zip (${SIZE}, permissions: 600)"

##############################################################################
# 5. Agent Packages
##############################################################################

log "[5/6] Backing up agent packages..."

if [ -d /opt/fim/agent ]; then
    cd /opt/fim
    zip -qr \
        "$BACKUP_DIR/fim_agents_${DATE}.zip" \
        agent/ \
        -x "agent/node_modules/*" \
        -x "agent/__pycache__/*" \
        || die "Agent zip failed"

    SIZE=$(du -sh "$BACKUP_DIR/fim_agents_${DATE}.zip" | awk '{print $1}')
    log "      OK  fim_agents_${DATE}.zip (${SIZE})"
else
    log "      SKIPPED (agent directory not found)"
fi

##############################################################################
# 6. Retention Cleanup
##############################################################################

log "[6/6] Removing backups older than ${KEEP_DAYS} days..."

find "$BACKUP_DIR" \
    -type f \
    -name "fim_*" \
    -mtime "+${KEEP_DAYS}" \
    -delete

COUNT=$(find "$BACKUP_DIR" -type f -name "fim_*" | wc -l)
log "      Remaining backup files: ${COUNT}"

##############################################################################
# Summary
##############################################################################

log ""
log "Backup Summary"
log "--------------"

ls -lh "$BACKUP_DIR"/*"${DATE}"* 2>/dev/null \
    | awk '{print "  " $5 "\t" $9}' \
    | tee -a "$LOG_FILE"

TOTAL=$(du -sh "$BACKUP_DIR" | awk '{print $1}')
log ""
log "Backup directory total: ${TOTAL}"
log "Backup completed successfully"
log "======================================================"
