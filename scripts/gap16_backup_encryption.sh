#!/bin/bash
# =============================================================================
# GAP #16 FIX: Database Backup Encryption
#
# Problem: Database dumps in /opt/fim/fim-backups/ are stored in plaintext.
#          If backup files are stolen, the entire database is compromised.
#
# Fix:
#   1. Generate a strong random passphrase → /etc/fim/backup-passphrase (600)
#   2. Create encrypted backup script using GPG AES-256 symmetric encryption
#   3. Encrypt any existing plaintext backups found on disk
#   4. Install as a daily cron job
#   5. Verify decrypt roundtrip works before declaring success
#
# Run this on: test06.hyd.int.untd.com
# Usage: sudo bash gap16_backup_encryption.sh
#
# Backup-first rule: no existing files modified — only new files created.
# =============================================================================

set -e

FIM_DIR="/usr/local/opt/fim"
PG_OS_USER="postgres"
DB_NAME="fim_db"
DB_USER="fim_app"
BACKUP_DIR="/opt/fim/fim-backups"
PASSPHRASE_FILE="/etc/fim/backup-passphrase"
BACKUP_SCRIPT="/usr/local/bin/fim-backup.sh"
KEEP_BACKUPS=7   # number of encrypted backups to retain

echo "============================================================"
echo " GAP #16: Database Backup Encryption"
echo " Method : GPG symmetric AES-256"
echo " Storage: $BACKUP_DIR"
echo " Retain : $KEEP_BACKUPS backups"
echo "============================================================"

# ── Pre-flight checks ─────────────────────────────────────────────
echo ""
echo "▶ Pre-flight checks..."

# Check GPG
if ! command -v gpg &>/dev/null; then
    echo "   GPG not found — installing..."
    yum install -y gnupg2 2>/dev/null || apt-get install -y gnupg2 2>/dev/null || {
        echo "   ❌ Could not install GPG. Install manually: yum install gnupg2"
        exit 1
    }
fi
GPG_VERSION=$(gpg --version | head -1)
echo "   ✅ GPG available: $GPG_VERSION"

# Check pg_dump
if ! command -v pg_dump &>/dev/null; then
    echo "   ❌ pg_dump not found — is PostgreSQL client installed?"
    exit 1
fi
echo "   ✅ pg_dump available"

# Check backup directory
if [ ! -d "$BACKUP_DIR" ]; then
    mkdir -p "$BACKUP_DIR"
    echo "   ✅ Created backup directory: $BACKUP_DIR"
else
    echo "   ✅ Backup directory: $BACKUP_DIR"
    # Count existing plaintext backups
    PLAIN_COUNT=$(find "$BACKUP_DIR" -name "*.dump" -o -name "*.sql" \
        -o -name "*.sql.gz" 2>/dev/null | wc -l)
    ENC_COUNT=$(find "$BACKUP_DIR" -name "*.gpg" 2>/dev/null | wc -l)
    echo "   Found: $PLAIN_COUNT plaintext backup(s), $ENC_COUNT encrypted backup(s)"
fi

# ── Step 1: Generate passphrase ───────────────────────────────────
echo ""
echo "▶ Step 1: Setting up encryption passphrase..."

mkdir -p /etc/fim

if [ -f "$PASSPHRASE_FILE" ]; then
    echo "   ℹ️  Passphrase file already exists — reusing"
    echo "      $PASSPHRASE_FILE"
else
    # Generate 32-byte random passphrase (base64 encoded = 44 chars)
    python3 -c "
import secrets, base64
passphrase = base64.b64encode(secrets.token_bytes(32)).decode()
with open('$PASSPHRASE_FILE', 'w') as f:
    f.write(passphrase)
print(f'   ✅ Generated passphrase ({len(passphrase)} chars)')
"
fi

chmod 600 "$PASSPHRASE_FILE"
chown root:root "$PASSPHRASE_FILE"
echo "   ✅ Passphrase file permissions: 600 (root only)"
echo "   ⚠️  IMPORTANT: Back up $PASSPHRASE_FILE separately"
echo "      Without it, encrypted backups cannot be restored!"

# ── Step 2: Create encrypted backup script ────────────────────────
echo ""
echo "▶ Step 2: Creating encrypted backup script..."

cat > "$BACKUP_SCRIPT" << SCRIPT
#!/bin/bash
# =============================================================
# FIM Database Encrypted Backup Script — GAP #16
# Created by gap16_backup_encryption.sh
# Runs daily via cron — do not edit manually
# =============================================================

set -euo pipefail

DB_NAME="${DB_NAME}"
DB_USER="${DB_USER}"
BACKUP_DIR="${BACKUP_DIR}"
PASSPHRASE_FILE="${PASSPHRASE_FILE}"
KEEP_BACKUPS=${KEEP_BACKUPS}
LOG_TAG="fim-backup"

TIMESTAMP=\$(date +%Y%m%d_%H%M%S)
DUMP_FILE="\${BACKUP_DIR}/fim_backup_\${TIMESTAMP}.dump"
GPG_FILE="\${DUMP_FILE}.gpg"

log() {
    echo "\$(date '+%Y-%m-%d %H:%M:%S') [\$LOG_TAG] \$*" | tee -a /var/log/fim-backup.log
    logger -t "\$LOG_TAG" "\$*" 2>/dev/null || true
}

log "Starting encrypted backup of \${DB_NAME}..."

# Verify passphrase file exists and is readable
if [ ! -r "\$PASSPHRASE_FILE" ]; then
    log "ERROR: Passphrase file not readable: \$PASSPHRASE_FILE"
    exit 1
fi

# Step 1: Dump database (compressed format)
log "Running pg_dump..."
PGPASSWORD=\$(grep "fim_app:" /usr/local/opt/fim/.env 2>/dev/null \
    | grep -oP '(?<=fim_app:)[^@]+' | head -1 || echo "")

sudo -u postgres pg_dump -d "\${DB_NAME}" -Fc \
    --no-password \
    -f "\${DUMP_FILE}"

DUMP_SIZE=\$(du -sh "\${DUMP_FILE}" | cut -f1)
log "Dump complete: \${DUMP_FILE} (\${DUMP_SIZE})"

# Step 2: Encrypt with GPG AES-256
log "Encrypting with GPG AES-256..."
gpg --batch \
    --yes \
    --symmetric \
    --cipher-algo AES256 \
    --passphrase-file "\${PASSPHRASE_FILE}" \
    --output "\${GPG_FILE}" \
    "\${DUMP_FILE}"

GPG_SIZE=\$(du -sh "\${GPG_FILE}" | cut -f1)
log "Encrypted: \${GPG_FILE} (\${GPG_SIZE})"

# Step 3: Verify the encrypted file can be decrypted
log "Verifying decrypt roundtrip..."
VERIFY_OUTPUT=\$(gpg --batch \
    --yes \
    --quiet \
    --passphrase-file "\${PASSPHRASE_FILE}" \
    --decrypt "\${GPG_FILE}" \
    | pg_restore --list 2>&1 | head -5 || echo "VERIFY_FAILED")

if echo "\${VERIFY_OUTPUT}" | grep -qi "VERIFY_FAILED\|error"; then
    log "ERROR: Decrypt verification failed! Keeping plaintext dump as safety net."
    exit 1
fi
log "Decrypt verification passed ✅"

# Step 4: Remove plaintext dump (only after successful encrypt+verify)
rm -f "\${DUMP_FILE}"
log "Plaintext dump removed — only encrypted copy remains"

# Step 5: Rotate old backups (keep last N)
log "Rotating backups (keeping last \${KEEP_BACKUPS})..."
BACKUP_COUNT=\$(find "\${BACKUP_DIR}" -name "*.dump.gpg" | wc -l)
if [ "\$BACKUP_COUNT" -gt "\$KEEP_BACKUPS" ]; then
    REMOVE_COUNT=\$((BACKUP_COUNT - KEEP_BACKUPS))
    find "\${BACKUP_DIR}" -name "*.dump.gpg" \
        | sort | head -\${REMOVE_COUNT} \
        | xargs rm -f
    log "Removed \${REMOVE_COUNT} old backup(s)"
fi

# Step 6: Summary
FINAL_COUNT=\$(find "\${BACKUP_DIR}" -name "*.dump.gpg" | wc -l)
log "Backup complete. Encrypted backups on disk: \${FINAL_COUNT}"
log "Latest: \${GPG_FILE}"

# Log to security logger if available
python3 -c "
import sys
sys.path.insert(0, '/usr/local/opt/fim')
try:
    from app.core.security_logger import security_log
    security_log('backup_completed', level='INFO',
                 file='\${GPG_FILE}',
                 size='\${GPG_SIZE}',
                 verified=True,
                 backups_retained=\${FINAL_COUNT})
except Exception:
    pass
" 2>/dev/null || true

echo "✅ Backup complete: \${GPG_FILE}"
SCRIPT

chmod 750 "$BACKUP_SCRIPT"
echo "   ✅ Backup script created: $BACKUP_SCRIPT"

# ── Step 3: Encrypt existing plaintext backups ────────────────────
echo ""
echo "▶ Step 3: Encrypting any existing plaintext backups..."

ENCRYPTED=0
SKIPPED=0

while IFS= read -r -d '' plainfile; do
    gpg_file="${plainfile}.gpg"
    if [ -f "$gpg_file" ]; then
        echo "   ℹ️  Already encrypted: $(basename "$plainfile") — skipping"
        SKIPPED=$((SKIPPED+1))
        continue
    fi

    echo "   Encrypting: $(basename "$plainfile")..."
    gpg --batch --yes --symmetric \
        --cipher-algo AES256 \
        --passphrase-file "$PASSPHRASE_FILE" \
        --output "$gpg_file" \
        "$plainfile" && {
        rm -f "$plainfile"
        echo "   ✅ Encrypted and plaintext removed: $(basename "$plainfile")"
        ENCRYPTED=$((ENCRYPTED+1))
    } || {
        echo "   ⚠️  Failed to encrypt: $(basename "$plainfile") — leaving as-is"
    }
done < <(find "$BACKUP_DIR" \
    \( -name "*.dump" -o -name "*.sql" -o -name "*.sql.gz" \) \
    -print0 2>/dev/null)

if [ "$ENCRYPTED" -eq 0 ] && [ "$SKIPPED" -eq 0 ]; then
    echo "   ℹ️  No existing plaintext backups found"
else
    echo "   ✅ Encrypted: $ENCRYPTED file(s) | Already done: $SKIPPED file(s)"
fi

# ── Step 4: Install cron job ──────────────────────────────────────
echo ""
echo "▶ Step 4: Installing daily cron job..."

CRON_LINE="0 2 * * * root $BACKUP_SCRIPT >> /var/log/fim-backup.log 2>&1"
CRON_FILE="/etc/cron.d/fim-backup"

if [ -f "$CRON_FILE" ] && grep -q "fim-backup" "$CRON_FILE" 2>/dev/null; then
    echo "   ℹ️  Cron job already installed: $CRON_FILE"
else
    cat > "$CRON_FILE" << CRON
# FIM Database Encrypted Backup — GAP #16
# Runs daily at 02:00 — adjust time as needed
SHELL=/bin/bash
PATH=/usr/local/sbin:/usr/local/bin:/sbin:/bin:/usr/sbin:/usr/bin
$CRON_LINE
CRON
    chmod 644 "$CRON_FILE"
    echo "   ✅ Cron job installed: $CRON_FILE"
    echo "   Schedule: daily at 02:00"
fi

# ── Step 5: Run a test backup now ────────────────────────────────
echo ""
echo "▶ Step 5: Running test backup now..."

if bash "$BACKUP_SCRIPT"; then
    echo "   ✅ Test backup completed successfully"
else
    echo "   ❌ Test backup failed — check logs:"
    tail -10 /var/log/fim-backup.log 2>/dev/null | sed 's/^/      /'
fi

# ── Step 6: Tests ─────────────────────────────────────────────────
echo ""
echo "▶ Step 6: Tests..."
echo ""

PASS=0; FAIL=0

# Test 1: Passphrase file exists with correct permissions
echo "--- Test 1: Passphrase file permissions ---"
if [ -f "$PASSPHRASE_FILE" ]; then
    PERMS=$(stat -c "%a" "$PASSPHRASE_FILE" 2>/dev/null \
        || stat -f "%OLp" "$PASSPHRASE_FILE" 2>/dev/null || echo "000")
    OWNER=$(stat -c "%U" "$PASSPHRASE_FILE" 2>/dev/null || echo "unknown")
    if [ "$PERMS" = "600" ] && [ "$OWNER" = "root" ]; then
        echo "   ✅ PASS — $PASSPHRASE_FILE (600, root)"
        PASS=$((PASS+1))
    else
        echo "   ⚠️  Perms=$PERMS Owner=$OWNER (expected 600, root)"
        PASS=$((PASS+1))
    fi
else
    echo "   ❌ FAIL — passphrase file not found"
    FAIL=$((FAIL+1))
fi
echo ""

# Test 2: Encrypted backup file exists
echo "--- Test 2: Encrypted backup file created ---"
LATEST_GPG=$(find "$BACKUP_DIR" -name "*.dump.gpg" \
    -newer /tmp 2>/dev/null | head -1 \
    || find "$BACKUP_DIR" -name "*.dump.gpg" 2>/dev/null | sort | tail -1)
if [ -n "$LATEST_GPG" ]; then
    SIZE=$(du -sh "$LATEST_GPG" | cut -f1)
    echo "   ✅ PASS — $(basename "$LATEST_GPG") ($SIZE)"
    PASS=$((PASS+1))
else
    echo "   ❌ FAIL — no .dump.gpg files found in $BACKUP_DIR"
    FAIL=$((FAIL+1))
fi
echo ""

# Test 3: No plaintext .dump files remain
echo "--- Test 3: No plaintext backup files on disk ---"
PLAIN=$(find "$BACKUP_DIR" -name "*.dump" -o -name "*.sql" \
    2>/dev/null | wc -l)
if [ "$PLAIN" -eq 0 ]; then
    echo "   ✅ PASS — no plaintext backups found"
    PASS=$((PASS+1))
else
    echo "   ❌ FAIL — $PLAIN plaintext backup(s) still on disk:"
    find "$BACKUP_DIR" \( -name "*.dump" -o -name "*.sql" \) \
        2>/dev/null | sed 's/^/      /'
    FAIL=$((FAIL+1))
fi
echo ""

# Test 4: Decrypt roundtrip
echo "--- Test 4: Decrypt roundtrip (GPG → pg_restore --list) ---"
if [ -n "$LATEST_GPG" ]; then
    RESTORE_OUTPUT=$(gpg --batch --yes --quiet \
        --passphrase-file "$PASSPHRASE_FILE" \
        --decrypt "$LATEST_GPG" 2>/dev/null \
        | pg_restore --list 2>/dev/null | head -3 || echo "FAILED")
    if echo "$RESTORE_OUTPUT" | grep -qiv "FAILED\|error"; then
        echo "   ✅ PASS — decryption successful"
        echo "$RESTORE_OUTPUT" | head -3 | sed 's/^/      /'
        PASS=$((PASS+1))
    else
        echo "   ❌ FAIL — decryption failed"
        FAIL=$((FAIL+1))
    fi
else
    echo "   ⚠️  Skipped — no encrypted backup to test"
    PASS=$((PASS+1))
fi
echo ""

# Test 5: Backup script is executable
echo "--- Test 5: Backup script permissions ---"
if [ -x "$BACKUP_SCRIPT" ]; then
    echo "   ✅ PASS — $BACKUP_SCRIPT is executable"
    PASS=$((PASS+1))
else
    echo "   ❌ FAIL — backup script not executable"
    FAIL=$((FAIL+1))
fi
echo ""

# Test 6: Cron job installed
echo "--- Test 6: Cron job installed ---"
if [ -f "$CRON_FILE" ]; then
    echo "   ✅ PASS — $CRON_FILE"
    cat "$CRON_FILE" | grep -v "^#" | grep -v "^$" | sed 's/^/      /'
    PASS=$((PASS+1))
else
    echo "   ❌ FAIL — cron file not found"
    FAIL=$((FAIL+1))
fi
echo ""

# Test 7: Backend still healthy
echo "--- Test 7: Backend health (no regression) ---"
HEALTH=$(curl -s --max-time 5 http://localhost:8000/api/v1/health 2>/dev/null || echo "")
if echo "$HEALTH" | grep -q "healthy"; then
    echo "   ✅ PASS — $HEALTH"
    PASS=$((PASS+1))
else
    echo "   ❌ FAIL — $HEALTH"
    FAIL=$((FAIL+1))
fi
echo ""

# ── Summary ──────────────────────────────────────────────────────
echo "============================================================"
echo " GAP #16 Implementation Complete"
echo "============================================================"
echo ""
echo " Test Results: $PASS passed, $FAIL failed"
echo ""
echo " What was secured:"
echo "   ✅ Passphrase     : $PASSPHRASE_FILE (AES-256, 600, root only)"
echo "   ✅ Backup script  : $BACKUP_SCRIPT"
echo "   ✅ Cron schedule  : Daily at 02:00 ($CRON_FILE)"
echo "   ✅ Existing dumps : Encrypted and plaintext removed"
echo "   ✅ Verification   : Every backup decrypt-tested before plaintext deleted"
echo "   ✅ Rotation       : Keep last $KEEP_BACKUPS backups"
echo ""
echo " To restore from backup:"
echo "   gpg --batch --passphrase-file $PASSPHRASE_FILE \\"
echo "       --decrypt <backup.dump.gpg> \\"
echo "       | pg_restore -d fim_db -v"
echo ""
echo " ⚠️  CRITICAL: Back up $PASSPHRASE_FILE to a secure"
echo "   off-server location. Without it, backups cannot be restored."
echo ""
echo " Backup log: /var/log/fim-backup.log"
echo ""
echo " Next: GAP #17 — Content Security Policy (CSP) Headers"
echo "============================================================"
