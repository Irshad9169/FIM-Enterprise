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
#   - pg_dump, pg_restore, zip, rsync, mail must be installed
#
# Offsite:
#   - SSH key auth must be configured from this host to RSYNC_HOST
#   - RSYNC_HOST / RSYNC_PATH / RSYNC_USER below must be set
#
# Alerts:
#   - ALERT_EMAIL below must be set to receive failure/success emails
#   - 'mail' command must be available (mailx / sendmail)
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
SCRIPT_NAME=$(basename "$0")
HOSTNAME=$(hostname -s)

DB_HOST="localhost"
DB_PORT="5432"
DB_NAME="fim_db"
DB_USER="fim_app"

# Use .pgpass for authentication — never hardcode passwords.
# File must be:  chmod 600 /opt/fim/.pgpass
export PGPASSFILE="/opt/fim/.pgpass"

# Offsite rsync — update host and path to match your environment
# Example from your usage:
#   rsync -av /backup/fim/fim_db_20260501.dump test05.hyd.int.untd.com:/fs/untd-1/fim-backups/
RSYNC_HOST="test05.hyd.int.untd.com"
RSYNC_PATH="/fs/untd-1/fim-backups"

# Alert email — receives failure and success summary emails
ALERT_EMAIL="mbaba@corp.untd.com"

##############################################################################
# Functions
##############################################################################

log() {
    echo "[$(date '+%F %T')] $*" | tee -a "$LOG_FILE"
}

# Accumulate log output in memory so we can attach it to alert emails
LOG_BUFFER=""
log_buf() {
    local msg="[$(date '+%F %T')] $*"
    echo "$msg" | tee -a "$LOG_FILE"
    LOG_BUFFER="${LOG_BUFFER}"$'\n'"$msg"
}

send_alert() {
    local subject="$1"
    local body="$2"
    echo "$body" | mail -s "$subject" "$ALERT_EMAIL" 2>/dev/null || \
        log "WARNING: Could not send alert email to $ALERT_EMAIL"
}

# Called on any exit — sends failure email if exit code is non-zero
on_exit() {
    local exit_code=$?
    rm -rf "$TMP_DIR" >/dev/null 2>&1 || true

    if [[ $exit_code -ne 0 ]]; then
        local subject="[BACKUP FAILED] FIM on ${HOSTNAME} — ${DATE}"
        local body
        body="FIM backup FAILED on host: ${HOSTNAME}
Timestamp : ${DATE}
Exit code : ${exit_code}
Log file  : ${LOG_FILE}

---- Last log output ----
${LOG_BUFFER}

Please investigate immediately."
        send_alert "$subject" "$body"
    fi
}

trap on_exit EXIT

die() {
    log_buf "ERROR: $*"
    exit 1
}

##############################################################################
# Pre-flight checks
##############################################################################

[[ -f "$PGPASSFILE" ]]                                          || die ".pgpass not found at $PGPASSFILE"
[[ -z "$(find "$PGPASSFILE" -perm 600 2>/dev/null)" ]]         && die "$PGPASSFILE must be chmod 600"
command -v pg_dump    >/dev/null 2>&1                           || die "pg_dump not found"
command -v pg_restore >/dev/null 2>&1                           || die "pg_restore not found"
command -v zip        >/dev/null 2>&1                           || die "zip not found"
command -v rsync      >/dev/null 2>&1                           || die "rsync not found"
command -v mail       >/dev/null 2>&1                           || log "WARNING: mail command not found — email alerts disabled"

mkdir -p "$BACKUP_DIR"
mkdir -p "$TMP_DIR"

log_buf "======================================================"
log_buf "FIM Enterprise Backup Started"
log_buf "Hostname  : ${HOSTNAME}"
log_buf "Timestamp : ${DATE}"
log_buf "Backup dir: ${BACKUP_DIR}"
log_buf "======================================================"

##############################################################################
# 1. PostgreSQL — Full Database (Custom Format)
##############################################################################

log_buf "[1/7] Backing up PostgreSQL database (full)..."

pg_dump \
    -h "$DB_HOST" \
    -p "$DB_PORT" \
    -U "$DB_USER" \
    -Fc \
    "$DB_NAME" \
    -f "$BACKUP_DIR/fim_db_${DATE}.dump" \
    || die "pg_dump (full) failed"

SIZE=$(du -sh "$BACKUP_DIR/fim_db_${DATE}.dump" | awk '{print $1}')
log_buf "      OK  fim_db_${DATE}.dump (${SIZE})"

##############################################################################
# 2. PostgreSQL — Dump Verification
##############################################################################

log_buf "[2/7] Verifying database dump integrity..."

pg_restore --list "$BACKUP_DIR/fim_db_${DATE}.dump" >/dev/null \
    || die "Dump verification failed — dump may be corrupt"

log_buf "      OK  Dump verified successfully"

##############################################################################
# 3. PostgreSQL — Schema Only
##############################################################################

log_buf "[3/7] Backing up PostgreSQL schema..."

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
log_buf "      OK  fim_schema_${DATE}.dump (${SIZE})"

##############################################################################
# 4. Application Code
##############################################################################

log_buf "[4/7] Backing up application code..."

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
log_buf "      OK  fim_code_${DATE}.zip (${SIZE})"

##############################################################################
# 5. Configurations and Secrets
##############################################################################

log_buf "[5/7] Backing up configurations..."

mkdir -p "$TMP_DIR/configs"

# Application configs
cp -a /opt/fim/.env                      "$TMP_DIR/configs/"       2>/dev/null || true
cp -a /opt/fim/config                    "$TMP_DIR/configs/"       2>/dev/null || true
cp -a /opt/fim/email_map.conf            "$TMP_DIR/configs/"       2>/dev/null || true
cp -a /opt/fim/fim-global-exclusions.txt "$TMP_DIR/configs/"       2>/dev/null || true

# Systemd service files
cp -a /etc/systemd/system/fim-*.service  "$TMP_DIR/configs/"       2>/dev/null || true

# Nginx
cp -a /etc/nginx/conf.d/fim*.conf        "$TMP_DIR/configs/"       2>/dev/null || true

# PostgreSQL configs
cp -a /var/lib/pgsql/15/data/postgresql.conf "$TMP_DIR/configs/"   2>/dev/null || true
cp -a /var/lib/pgsql/15/data/pg_hba.conf     "$TMP_DIR/configs/"   2>/dev/null || true
cp -a /var/lib/pgsql/15/data/pg_ident.conf   "$TMP_DIR/configs/"   2>/dev/null || true

cd "$TMP_DIR"
zip -qr \
    "$BACKUP_DIR/fim_configs_${DATE}.zip" \
    configs/ \
    || die "Config zip failed"

chmod 600 "$BACKUP_DIR/fim_configs_${DATE}.zip"

SIZE=$(du -sh "$BACKUP_DIR/fim_configs_${DATE}.zip" | awk '{print $1}')
log_buf "      OK  fim_configs_${DATE}.zip (${SIZE}, permissions: 600)"

##############################################################################
# 5b. Agent Packages
##############################################################################

log_buf "[5b] Backing up agent packages..."

if [ -d /opt/fim/agent ]; then
    cd /opt/fim
    zip -qr \
        "$BACKUP_DIR/fim_agents_${DATE}.zip" \
        agent/ \
        -x "agent/node_modules/*" \
        -x "agent/__pycache__/*" \
        || die "Agent zip failed"

    SIZE=$(du -sh "$BACKUP_DIR/fim_agents_${DATE}.zip" | awk '{print $1}')
    log_buf "      OK  fim_agents_${DATE}.zip (${SIZE})"
else
    log_buf "      SKIPPED (agent directory not found)"
fi

##############################################################################
# 6. Offsite Rsync
##############################################################################

log_buf "[6/7] Syncing backups to offsite server (${RSYNC_HOST})..."

rsync \
    -av \
    --stats \
    "$BACKUP_DIR/" \
    "${RSYNC_HOST}:${RSYNC_PATH}/" \
    >> "$LOG_FILE" 2>&1 \
    || die "Offsite rsync to ${RSYNC_HOST} failed"

log_buf "      OK  Offsite sync complete → ${RSYNC_HOST}:${RSYNC_PATH}"

##############################################################################
# 7. Retention Cleanup
##############################################################################

log_buf "[7/7] Removing local backups older than ${KEEP_DAYS} days..."

find "$BACKUP_DIR" \
    -type f \
    -name "fim_*" \
    -mtime "+${KEEP_DAYS}" \
    -delete

COUNT=$(find "$BACKUP_DIR" -type f -name "fim_*" | wc -l)
log_buf "      Remaining local backup files: ${COUNT}"

##############################################################################
# Summary + Success Email
##############################################################################

SUMMARY=$(ls -lh "$BACKUP_DIR"/*"${DATE}"* 2>/dev/null \
    | awk '{print "  " $5 "\t" $9}')

TOTAL=$(du -sh "$BACKUP_DIR" | awk '{print $1}')

log_buf ""
log_buf "Backup Summary"
log_buf "--------------"
echo "$SUMMARY" | tee -a "$LOG_FILE"
log_buf ""
log_buf "Backup directory total : ${TOTAL}"
log_buf "Offsite                : ${RSYNC_HOST}:${RSYNC_PATH}"
log_buf "Backup completed successfully"
log_buf "======================================================"

# Send success email
send_alert "[BACKUP OK] FIM on ${HOSTNAME} — ${DATE}" \
"FIM backup completed successfully on host: ${HOSTNAME}
Timestamp  : ${DATE}
Local dir  : ${BACKUP_DIR}  (${TOTAL} total)
Offsite    : ${RSYNC_HOST}:${RSYNC_PATH}
Log file   : ${LOG_FILE}

---- Files created ----
${SUMMARY}

Backup verified (pg_restore --list passed).
Retention: backups older than ${KEEP_DAYS} days removed. ${COUNT} files remaining."
