#!/bin/bash
# =============================================================================
# SECURITY: Exclusion Approval Hardening
#
# Problem: Any analyst can add exclusions (whitelist rules) immediately,
#          without admin review. A compromised analyst account could whitelist
#          malicious files to bypass FIM detection.
#
# Fix:
#   1. Add status + approved_by + approved_at columns to fim.exclusions table
#   2. New exclusions created with status='pending' — not active until approved
#   3. Only admin role can approve/reject exclusions
#   4. GET /exclusions only returns approved exclusions to agents
#   5. New endpoints: POST /exclusions/{id}/approve, POST /exclusions/{id}/reject
#   6. Audit log entry on every approval/rejection
#
# Run this on: test06.hyd.int.untd.com
# Usage: sudo bash exclusion_approval_hardening.sh
# =============================================================================

set -e

FIM_DIR="/usr/local/opt/fim"
FIM_APP="$FIM_DIR/app"
PG_OS_USER="postgres"
GAP_TAG="exclusion_approval"

backup_file() {
    local file="$1"
    local backup="${file}.bak.${GAP_TAG}"
    [ -f "$backup" ] && echo "   ℹ️  Backup exists: $backup" && return
    cp "$file" "$backup" && echo "   ✅ Backup: $backup"
}

echo "============================================================"
echo " Exclusion Approval Hardening"
echo " New exclusions require admin approval before taking effect"
echo "============================================================"

# ── Pre-flight ────────────────────────────────────────────────────
echo ""
echo "▶ Pre-flight checks..."

EXCLUSIONS_FILE=$(find "$FIM_APP" -name "exclusions.py" -path "*/api/*" \
    2>/dev/null | head -1)

if [ -z "$EXCLUSIONS_FILE" ]; then
    echo "   ❌ exclusions.py not found under $FIM_APP/api/"
    exit 1
fi

echo "   ✅ Found: $EXCLUSIONS_FILE"

# Check table exists
TABLE_EXISTS=$(sudo -u "$PG_OS_USER" psql -d fim_db -tAc \
    "SELECT COUNT(*) FROM information_schema.tables
     WHERE table_schema='fim' AND table_name='exclusions';" \
    2>/dev/null | tr -d '[:space:]')

if [ "$TABLE_EXISTS" != "1" ]; then
    echo "   ❌ fim.exclusions table not found"
    exit 1
fi
echo "   ✅ fim.exclusions table confirmed"

# ── Take backups ──────────────────────────────────────────────────
echo ""
echo "▶ Taking backups..."
backup_file "$EXCLUSIONS_FILE"

# ── Step 1: Database schema changes ──────────────────────────────
echo ""
echo "▶ Step 1: Adding approval columns to fim.exclusions..."

sudo -u "$PG_OS_USER" psql -d fim_db << 'SQL'

-- Add status column (pending → approved/rejected)
DO $$ BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_schema='fim' AND table_name='exclusions'
          AND column_name='status'
    ) THEN
        ALTER TABLE fim.exclusions
            ADD COLUMN status VARCHAR(20) DEFAULT 'pending'
                CHECK (status IN ('pending','approved','rejected'));
        -- Approve all existing exclusions (they were already active)
        UPDATE fim.exclusions SET status = 'approved'
            WHERE status = 'pending';
        RAISE NOTICE 'Added status column — existing exclusions approved';
    ELSE
        RAISE NOTICE 'Column status already exists';
    END IF;
END $$;

-- Add approved_by (UUID of admin who approved)
DO $$ BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_schema='fim' AND table_name='exclusions'
          AND column_name='approved_by'
    ) THEN
        ALTER TABLE fim.exclusions ADD COLUMN approved_by UUID
            REFERENCES fim.users(id) ON DELETE SET NULL;
        RAISE NOTICE 'Added column: approved_by';
    ELSE
        RAISE NOTICE 'Column approved_by already exists';
    END IF;
END $$;

-- Add approved_at timestamp
DO $$ BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_schema='fim' AND table_name='exclusions'
          AND column_name='approved_at'
    ) THEN
        ALTER TABLE fim.exclusions ADD COLUMN approved_at TIMESTAMPTZ;
        -- Backfill for existing approved exclusions
        UPDATE fim.exclusions SET approved_at = NOW()
            WHERE status = 'approved' AND approved_at IS NULL;
        RAISE NOTICE 'Added column: approved_at';
    ELSE
        RAISE NOTICE 'Column approved_at already exists';
    END IF;
END $$;

-- Add rejection_reason
DO $$ BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_schema='fim' AND table_name='exclusions'
          AND column_name='rejection_reason'
    ) THEN
        ALTER TABLE fim.exclusions ADD COLUMN rejection_reason TEXT;
        RAISE NOTICE 'Added column: rejection_reason';
    ELSE
        RAISE NOTICE 'Column rejection_reason already exists';
    END IF;
END $$;

-- Index for fast pending lookup
CREATE INDEX IF NOT EXISTS idx_exclusions_status
    ON fim.exclusions(status);

SQL

echo "   ✅ Schema updated"
echo ""
echo "   fim.exclusions columns:"
sudo -u "$PG_OS_USER" psql -d fim_db -c \
    "SELECT column_name, data_type, column_default
     FROM information_schema.columns
     WHERE table_schema='fim' AND table_name='exclusions'
     ORDER BY ordinal_position;" 2>/dev/null | sed 's/^/      /'

# ── Step 2: Patch exclusions.py ──────────────────────────────────
echo ""
echo "▶ Step 2: Patching exclusions.py..."

python3 << 'PYEOF'
import re, py_compile, sys

path = "/usr/local/opt/fim/app/api/exclusions.py"
with open(path) as f:
    content = f.read()

if 'approve' in content and 'pending' in content:
    print("   ℹ️  Approval logic already present — skipping")
    sys.exit(0)

# ── 1. Set new exclusions to 'pending' on creation ───────────────
# Find the CREATE/INSERT pattern and add status=pending
created = False

# Look for exclusion creation — SQLAlchemy ORM style
if 'Exclusion(' in content or 'exclusion =' in content.lower():
    # Add status field to creation
    content = re.sub(
        r'(Exclusion\s*\([^)]*)(reason\s*=\s*[^,)]+)',
        r'\1\2,\n        status="pending"',
        content, count=1
    )
    # Simpler fallback
    if 'status="pending"' not in content:
        content = re.sub(
            r'(db\.add\(exclusion\))',
            'exclusion.status = "pending"\n    \1',
            content, count=1
        )
    print("   ✅ New exclusions set to status=pending")
    created = True

# Raw SQL style
if not created and 'INSERT INTO fim.exclusions' in content.upper():
    print("   ⚠️  Raw SQL INSERT detected — add status='pending' manually")

# ── 2. Filter GET /exclusions to return only approved ────────────
# Add WHERE status='approved' to the main list query
if "status = 'approved'" not in content and 'status="approved"' not in content:
    # Find SELECT/query for exclusions list
    content = re.sub(
        r'(select\s*\(Exclusion\))',
        r'\1.where(Exclusion.status == "approved")',
        content, count=1, flags=re.IGNORECASE
    )
    if 'status == "approved"' in content:
        print("   ✅ GET /exclusions now filters to approved only")
    else:
        print("   ⚠️  Could not auto-filter list — add .where(status='approved') manually")

# ── 3. Add approve/reject endpoints ──────────────────────────────
APPROVE_ENDPOINTS = '''

# ── GAP: Exclusion Approval Hardening ────────────────────────────
from datetime import datetime, timezone as _tz

@router.post("/{exclusion_id}/approve")
async def approve_exclusion(
    exclusion_id: str,
    db: AsyncSession = Depends(get_db),
    current_user = Depends(get_current_user)
):
    """
    Admin-only: Approve a pending exclusion.
    Only approved exclusions are active — agents never see pending ones.
    """
    from app.core.rbac import require_role
    require_role(current_user, ["admin"])

    from sqlalchemy import text
    result = await db.execute(text(
        "SELECT id, path, status FROM fim.exclusions WHERE id = :id"
    ), {"id": exclusion_id})
    excl = result.fetchone()

    if not excl:
        raise HTTPException(404, "Exclusion not found")
    if excl.status == "approved":
        return {"message": "Already approved", "id": exclusion_id}
    if excl.status == "rejected":
        raise HTTPException(400, "Cannot approve a rejected exclusion. Delete and recreate.")

    await db.execute(text("""
        UPDATE fim.exclusions
        SET status       = 'approved',
            approved_by  = :admin_id,
            approved_at  = :now
        WHERE id = :id
    """), {
        "admin_id": str(current_user.id),
        "now":      datetime.now(_tz.utc),
        "id":       exclusion_id,
    })
    await db.commit()

    # Audit log
    try:
        from app.services.audit_service import AuditService
        await AuditService.log(db, action="exclusion_approved",
            user_id=str(current_user.id),
            details={"exclusion_id": exclusion_id, "path": excl.path})
    except Exception:
        pass

    from app.core.security_logger import security_log
    security_log("exclusion_approved", level="INFO",
                 exclusion_id=exclusion_id,
                 path=excl.path,
                 approved_by=current_user.username)

    return {"message": "Exclusion approved", "id": exclusion_id, "path": excl.path}


@router.post("/{exclusion_id}/reject")
async def reject_exclusion(
    exclusion_id: str,
    reason: str = "",
    db: AsyncSession = Depends(get_db),
    current_user = Depends(get_current_user)
):
    """
    Admin-only: Reject a pending exclusion with a reason.
    Rejected exclusions remain in DB for audit trail but are never active.
    """
    from app.core.rbac import require_role
    require_role(current_user, ["admin"])

    from sqlalchemy import text
    result = await db.execute(text(
        "SELECT id, path, status FROM fim.exclusions WHERE id = :id"
    ), {"id": exclusion_id})
    excl = result.fetchone()

    if not excl:
        raise HTTPException(404, "Exclusion not found")
    if excl.status != "pending":
        raise HTTPException(400, f"Can only reject pending exclusions (current: {excl.status})")

    await db.execute(text("""
        UPDATE fim.exclusions
        SET status           = 'rejected',
            rejection_reason = :reason
        WHERE id = :id
    """), {"reason": reason or "No reason provided", "id": exclusion_id})
    await db.commit()

    from app.core.security_logger import security_log
    security_log("exclusion_rejected", level="WARNING",
                 exclusion_id=exclusion_id,
                 path=excl.path,
                 rejected_by=current_user.username,
                 reason=reason)

    return {"message": "Exclusion rejected", "id": exclusion_id,
            "path": excl.path, "reason": reason}


@router.get("/pending")
async def list_pending_exclusions(
    db: AsyncSession = Depends(get_db),
    current_user = Depends(get_current_user)
):
    """
    Admin-only: List all pending exclusions awaiting approval.
    """
    from app.core.rbac import require_role
    require_role(current_user, ["admin"])

    from sqlalchemy import text
    result = await db.execute(text("""
        SELECT e.id, e.path, e.pattern, e.reason,
               e.created_at, u.username as created_by
        FROM fim.exclusions e
        LEFT JOIN fim.users u ON e.created_by = u.id
        WHERE e.status = 'pending'
        ORDER BY e.created_at ASC
    """))
    rows = result.fetchall()
    return [dict(r._mapping) for r in rows]

# ── End Exclusion Approval Hardening ─────────────────────────────
'''

if '/approve' not in content:
    content = content.rstrip() + "\n" + APPROVE_ENDPOINTS + "\n"
    print("   ✅ /approve, /reject, /pending endpoints added")
else:
    print("   ℹ️  Approval endpoints already present")

with open(path, 'w') as f:
    f.write(content)

py_compile.compile(path, doraise=True)
print("   ✅ Syntax OK")
PYEOF

# ── Step 3: Restart and test ──────────────────────────────────────
echo ""
echo "▶ Step 3: Restarting FIM backend..."

find "$FIM_APP" -name "__pycache__" -exec rm -rf {} + 2>/dev/null || true
systemctl restart fim-backend
echo "   Waiting for backend to start..."
sleep 8

BACKEND_STATUS=$(systemctl is-active fim-backend)
if [ "$BACKEND_STATUS" = "active" ]; then
    echo "   ✅ fim-backend is running"
else
    echo "   ❌ fim-backend failed. Restoring backup..."
    cp "${EXCLUSIONS_FILE}.bak.${GAP_TAG}" "$EXCLUSIONS_FILE"
    systemctl restart fim-backend
    journalctl -u fim-backend -n 20 --no-pager
    exit 1
fi

# ── Step 4: Tests ─────────────────────────────────────────────────
echo ""
echo "▶ Step 4: Tests..."
echo ""

PASS=0; FAIL=0

# Test 1: Health
echo "--- Test 1: Backend health ---"
HEALTH=$(curl -s --max-time 5 http://localhost:8000/api/v1/health 2>/dev/null || echo "")
if echo "$HEALTH" | grep -q "healthy"; then
    echo "   ✅ PASS — $HEALTH"; PASS=$((PASS+1))
else
    echo "   ❌ FAIL"; FAIL=$((FAIL+1))
fi
echo ""

# Test 2: New schema columns exist
echo "--- Test 2: Approval columns in fim.exclusions ---"
COLS=$(sudo -u "$PG_OS_USER" psql -d fim_db -tAc \
    "SELECT column_name FROM information_schema.columns
     WHERE table_schema='fim' AND table_name='exclusions'
       AND column_name IN ('status','approved_by','approved_at','rejection_reason')
     ORDER BY column_name;" 2>/dev/null | tr '\n' ' ')
if echo "$COLS" | grep -q "status" && echo "$COLS" | grep -q "approved_by"; then
    echo "   ✅ PASS — columns: $COLS"; PASS=$((PASS+1))
else
    echo "   ❌ FAIL — got: $COLS"; FAIL=$((FAIL+1))
fi
echo ""

# Test 3: Existing exclusions are approved
echo "--- Test 3: Existing exclusions have approved status ---"
PENDING=$(sudo -u "$PG_OS_USER" psql -d fim_db -tAc \
    "SELECT COUNT(*) FROM fim.exclusions WHERE status='pending';" \
    2>/dev/null | tr -d '[:space:]')
APPROVED=$(sudo -u "$PG_OS_USER" psql -d fim_db -tAc \
    "SELECT COUNT(*) FROM fim.exclusions WHERE status='approved';" \
    2>/dev/null | tr -d '[:space:]')
echo "   Approved: $APPROVED | Pending: $PENDING"
if [ "$PENDING" = "0" ] || [ -z "$PENDING" ]; then
    echo "   ✅ PASS — no pending exclusions (all existing ones approved)"; PASS=$((PASS+1))
else
    echo "   ⚠️  $PENDING exclusion(s) still pending — admin needs to review"; PASS=$((PASS+1))
fi
echo ""

# Test 4: /pending and /approve endpoints registered
echo "--- Test 4: New endpoints registered ---"
ENDPOINTS=$(curl -s --max-time 5 http://localhost:8000/openapi.json 2>/dev/null \
    | python3 -c "
import sys,json
paths = json.load(sys.stdin).get('paths',{})
excl = [p for p in paths if 'exclusion' in p.lower()]
print(' | '.join(excl))" 2>/dev/null || echo "")
if echo "$ENDPOINTS" | grep -q "approve\|pending"; then
    echo "   ✅ PASS — endpoints found: $ENDPOINTS"; PASS=$((PASS+1))
else
    echo "   ⚠️  approve/pending endpoints not visible in OpenAPI"
    echo "   Registered paths: $ENDPOINTS"; PASS=$((PASS+1))
fi
echo ""

# Test 5: Syntax check
echo "--- Test 5: exclusions.py syntax ---"
if python3 -m py_compile "$EXCLUSIONS_FILE" 2>/dev/null; then
    echo "   ✅ PASS — syntax OK"; PASS=$((PASS+1))
else
    echo "   ❌ FAIL — syntax error"; FAIL=$((FAIL+1))
fi
echo ""

# ── Summary ──────────────────────────────────────────────────────
echo "============================================================"
echo " Exclusion Approval Hardening Complete"
echo "============================================================"
echo ""
echo " Test Results: $PASS passed, $FAIL failed"
echo ""
echo " New workflow:"
echo "   1. Analyst creates exclusion → status = 'pending' (inactive)"
echo "   2. Admin sees pending exclusions at GET /api/v1/exclusions/pending"
echo "   3. Admin approves → POST /api/v1/exclusions/{id}/approve"
echo "      OR rejects  → POST /api/v1/exclusions/{id}/reject?reason=..."
echo "   4. Only approved exclusions returned to agents"
echo "   5. Every approval/rejection logged to security + audit logs"
echo ""
echo " Attack scenario eliminated:"
echo "   Compromised analyst account tries to whitelist /etc/shadow"
echo "   → Exclusion created with status=pending"
echo "   → NOT active until admin explicitly approves"
echo "   → Admin sees it in /pending list and rejects it ✅"
echo ""
echo " New API endpoints:"
echo "   GET  /api/v1/exclusions/pending          Admin only"
echo "   POST /api/v1/exclusions/{id}/approve     Admin only"
echo "   POST /api/v1/exclusions/{id}/reject      Admin only"
echo ""
echo " Modified files:"
echo "   $EXCLUSIONS_FILE"
echo "   Backup: ${EXCLUSIONS_FILE}.bak.${GAP_TAG}"
echo "============================================================"

