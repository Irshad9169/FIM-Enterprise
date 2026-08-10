#!/bin/bash
# =============================================================================
# FIM Disk Cleanup — runs via cron, keeps disk healthy
# Cron: 0 3 * * * root bash /usr/local/bin/fim-disk-cleanup.sh
# =============================================================================

LOG=/var/log/fim-disk-cleanup.log
DATE=$(date "+%Y-%m-%d %H:%M:%S")
BACKUP_DIR="/opt/fim/fim-backups"
KEEP_BACKUPS=2
MIN_FREE_GB=4

log() { echo "[$DATE] $1" | tee -a "$LOG"; }

# Read thresholds from fim.system_settings (same table the System Health
# page's sliders write to) so an admin adjusting them in the UI actually
# changes this script's behavior too, not just the dashboard display.
# Falls back to the same 85/92 defaults if the DB is unreachable -- this
# script must still degrade gracefully rather than fail outright, since
# "the database is having problems" is exactly one situation it needs to
# keep working in.
export PGPASSFILE=/opt/fim/.pgpass
WARN_PCT=$(psql -h localhost -U fim_app -d fim_db -tAc \
    "SELECT disk_warning_pct FROM fim.system_settings LIMIT 1;" 2>/dev/null | tr -d ' ')
CRIT_PCT=$(psql -h localhost -U fim_app -d fim_db -tAc \
    "SELECT disk_critical_pct FROM fim.system_settings LIMIT 1;" 2>/dev/null | tr -d ' ')
WARN_PCT=${WARN_PCT%.*}
CRIT_PCT=${CRIT_PCT%.*}
[ -z "$WARN_PCT" ] && WARN_PCT=85
[ -z "$CRIT_PCT" ] && CRIT_PCT=92

USED=$(df --output=pcent / | tail -1 | tr -d " %")
AVAIL_KB=$(df --output=avail / | tail -1 | tr -d " ")
AVAIL_GB=$((AVAIL_KB / 1024 / 1024))

log "Disk: ${USED}% used, ${AVAIL_GB}GB free"

# ── 1. Always: rotate backups to KEEP_BACKUPS ────────────────────
REMOVED=$(ls -t "${BACKUP_DIR}"/*.gpg 2>/dev/null | tail -n +$((KEEP_BACKUPS + 1)) | wc -l)
ls -t "${BACKUP_DIR}"/*.gpg 2>/dev/null | tail -n +$((KEEP_BACKUPS + 1)) | xargs rm -f 2>/dev/null
rm -f "${BACKUP_DIR}"/*.dump 2>/dev/null
[ "$REMOVED" -gt 0 ] && log "Rotated $REMOVED old backup(s) — kept last $KEEP_BACKUPS"

# ── 2. Always: clean pycache ─────────────────────────────────────
find /usr/local/opt/fim/app -name "__pycache__" -exec rm -rf {} + 2>/dev/null || true

# ── 2b. Always: null out old scan_data + vacuum fim.scans ────────
# Routine hygiene, not threshold-gated -- this is what actually prevents
# fim.scans from silently regrowing (see migration 0011 and the incident
# it followed: 27GB of dead TOAST from scan_data being nulled without
# ever being vacuumed). Runs daily regardless of current disk pressure,
# same as backup rotation above.
if [ -x /usr/local/bin/cleanup_scan_data.sh ]; then
    /usr/local/bin/cleanup_scan_data.sh >> "$LOG" 2>&1
    log "Ran cleanup_scan_data.sh (scan_data retention + VACUUM)"
else
    log "WARNING: /usr/local/bin/cleanup_scan_data.sh not found — scan_data retention skipped"
fi

# ── 3. Warning threshold ──────────────────────────────────────────
if [ "$USED" -gt "$WARN_PCT" ]; then
    log "WARNING: disk at ${USED}% (threshold ${WARN_PCT}%) — running additional cleanup"

    # Trim journal to 200MB
    journalctl --vacuum-size=200M >> "$LOG" 2>&1

    # Truncate nginx logs (they rotate anyway)
    [ -f /var/log/nginx/access.log ] && > /var/log/nginx/access.log
    [ -f /var/log/nginx/error.log  ] && > /var/log/nginx/error.log

    log "After warning cleanup: $(df --output=pcent / | tail -1 | tr -d ' ') used"
fi

# ── 4. Critical threshold ─────────────────────────────────────────
if [ "$USED" -gt "$CRIT_PCT" ]; then
    log "CRITICAL: disk at ${USED}% (threshold ${CRIT_PCT}%) — emergency cleanup"

    # Keep only 1 backup
    ls -t "${BACKUP_DIR}"/*.gpg 2>/dev/null | tail -n +2 | xargs rm -f 2>/dev/null
    log "Emergency: kept only 1 backup"

    # Aggressive journal trim
    journalctl --vacuum-size=50M >> "$LOG" 2>&1

    # Remove npm cache
    npm cache clean --force >> "$LOG" 2>&1

    log "After emergency cleanup: $(df --output=pcent / | tail -1 | tr -d ' ') used"

    # Alert via fim security log
    echo "[$DATE] DISK CRITICAL ${USED}% — emergency cleanup ran" \
        >> /var/log/fim-security.log 2>/dev/null || true
fi

# ── 5. Final status ──────────────────────────────────────────────
USED_AFTER=$(df --output=pcent / | tail -1 | tr -d " %")
AVAIL_AFTER=$(($(df --output=avail / | tail -1 | tr -d " ") / 1024 / 1024))
log "Done. Disk: ${USED_AFTER}% used, ${AVAIL_AFTER}GB free"
log "Backups kept: $(ls "${BACKUP_DIR}"/*.gpg 2>/dev/null | wc -l)"
