from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, desc, text
from pydantic import BaseModel
from typing import Optional
import uuid
import json
import hashlib
import logging
from datetime import datetime

from app.core.database import get_db
from app.core.security import get_current_user
from app.core.rbac import analyst_plus
from app.models.models import User, Baseline
from app.services.audit_service import AuditService
from app.services.baseline_version_control import snapshot_baseline, get_baseline_history, get_snapshot_content, snapshot_all_approved_baselines
from app.services.diff_signing import sign_diff, verify_diff_signature, create_signed_diff_response

logger = logging.getLogger(__name__)
router = APIRouter()


def _client_ip(request: Request) -> str:
    forwarded = request.headers.get("x-forwarded-for")
    if forwarded:
        return forwarded.split(",")[0].strip()
    return request.client.host if request.client else ""


class RebaselineRequest(BaseModel):
    justification: str
    keep_old: bool = False  # If true, keep old baseline for audit trail


class ApproveBaselineRequest(BaseModel):
    notes: Optional[str] = None


# ── List Baselines ────────────────────────────────────────────────────────

@router.get("")
async def list_baselines(db: AsyncSession = Depends(get_db), u=Depends(get_current_user)):
    result = await db.execute(text("""
        SELECT b.id, b.agent_id, b.status, b.is_active, b.is_approved,
               b.created_at, b.file_count, b.notes, b.checksum,
               b.approved_at, b.approved_by,
               a.hostname as agent_hostname,
               u.username as approved_by_name
        FROM fim.baselines b
        LEFT JOIN fim.agents a ON b.agent_id = a.id
        LEFT JOIN fim.users u ON b.approved_by = u.id
        ORDER BY b.created_at DESC
    """))
    baselines = []
    for b in result.fetchall():
        baselines.append({
            "id": str(b.id),
            "agent_id": str(b.agent_id),
            "agent_hostname": b.agent_hostname or "unknown",
            "status": b.status or ("approved" if b.is_approved else "pending"),
            "is_active": b.is_active,
            "file_count": b.file_count or 0,
            "notes": b.notes,
            "checksum": b.checksum[:16] + "..." if b.checksum else None,
            "created_at": b.created_at.isoformat() if b.created_at else None,
            "approved_at": b.approved_at.isoformat() if b.approved_at else None,
            "approved_by_name": b.approved_by_name,
        })
    return {"baselines": baselines}


# ── Approve Baseline ──────────────────────────────────────────────────────

@router.post("/{baseline_id}/approve")
async def approve_baseline(
    baseline_id: str,
    request: Request,
    body: Optional[ApproveBaselineRequest] = None,
    db: AsyncSession = Depends(get_db),
    u=Depends(analyst_plus)
):
    """Approve a baseline and make it active. Deactivates any other active baseline for same agent."""
    try:
        bid = uuid.UUID(baseline_id)
    except ValueError:
        raise HTTPException(400, "Invalid baseline ID")

    # Get the baseline
    result = await db.execute(select(Baseline).where(Baseline.id == bid))
    baseline = result.scalar_one_or_none()
    if not baseline:
        raise HTTPException(404, "Baseline not found")

    if baseline.status == "approved" and baseline.is_active:
        raise HTTPException(400, "Baseline is already approved and active")

    # Deactivate any other active baselines for this agent
    await db.execute(text("""
        UPDATE fim.baselines
        SET is_active = false
        WHERE agent_id = :agent_id AND is_active = true AND id != :id
    """), {"agent_id": str(baseline.agent_id), "id": baseline_id})

    # Recompute checksum for integrity
    if baseline.baseline_data:
        data_str = json.dumps(baseline.baseline_data, sort_keys=True, separators=(",", ":"))
        checksum = hashlib.sha256(data_str.encode("utf-8")).hexdigest()
    else:
        checksum = baseline.checksum

    # Approve
    notes = body.notes if body else None
    await db.execute(text("""
        UPDATE fim.baselines
        SET status = 'approved', is_approved = true, is_active = true,
            approved_at = NOW(), approved_by = :uid, checksum = :checksum,
            notes = COALESCE(:notes, notes)
        WHERE id = :id
    """), {"uid": u.id, "id": baseline_id, "checksum": checksum, "notes": notes})

    # Audit
    await AuditService.log(
        db, u.id, u.username, "APPROVE_BASELINE",
        resource_type="baseline", resource_id=bid,
        details={"agent_id": str(baseline.agent_id), "notes": notes},
        ip_address=_client_ip(request),
    )

    await db.commit()
    return {"message": "Baseline approved", "checksum": checksum[:16] + "..."}


# ── Re-baseline (Request New Baseline from Latest Scan) ──────────────────

@router.post("/{baseline_id}/rebaseline")
async def rebaseline(
    baseline_id: str,
    req: RebaselineRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
    u=Depends(analyst_plus)
):
    """
    Create a new baseline from the latest scan data for the same agent.
    The old baseline is deactivated (or kept for audit if keep_old=true).
    The new baseline starts as 'pending' and must be approved.
    """
    try:
        bid = uuid.UUID(baseline_id)
    except ValueError:
        raise HTTPException(400, "Invalid baseline ID")

    # Get current baseline
    result = await db.execute(select(Baseline).where(Baseline.id == bid))
    old_baseline = result.scalar_one_or_none()
    if not old_baseline:
        raise HTTPException(404, "Baseline not found")

    # Get latest completed scan for this agent
    scan_result = await db.execute(text("""
        SELECT id, scan_data, files_scanned, completed_at
        FROM fim.scans
        WHERE agent_id = :agent_id AND status = 'completed'
        ORDER BY completed_at DESC
        LIMIT 1
    """), {"agent_id": str(old_baseline.agent_id)})
    latest_scan = scan_result.fetchone()

    if not latest_scan or not latest_scan.scan_data:
        raise HTTPException(400, "No completed scan data available for this agent")

    # Compute checksum for new baseline
    data_str = json.dumps(latest_scan.scan_data, sort_keys=True, separators=(",", ":"))
    checksum = hashlib.sha256(data_str.encode("utf-8")).hexdigest()

    # Deactivate old baseline
    old_status = "superseded" if req.keep_old else "replaced"
    await db.execute(text("""
        UPDATE fim.baselines
        SET is_active = false, status = :status
        WHERE id = :id
    """), {"id": baseline_id, "status": old_status})

    # Create new baseline
    new_id = uuid.uuid4()
    await db.execute(text("""
        INSERT INTO fim.baselines (
            id, agent_id, baseline_name, baseline_data, file_count,
            total_size_bytes, checksum, is_active, status,
            is_approved, created_at, created_by, notes
        ) VALUES (
            :id, :agent_id, :name, CAST(:data AS jsonb), :file_count,
            0, :checksum, false, 'pending',
            false, NOW(), :created_by, :notes
        )
    """), {
        "id": str(new_id),
        "agent_id": str(old_baseline.agent_id),
        "name": f"Re-baseline - {datetime.now().strftime('%Y-%m-%d %H:%M')}",
        "data": json.dumps(latest_scan.scan_data),
        "file_count": latest_scan.files_scanned,
        "checksum": checksum,
        "created_by": str(u.id),
        "notes": f"Re-baseline requested by {u.username}: {req.justification}",
    })

    # Audit
    await AuditService.log(
        db, u.id, u.username, "REBASELINE",
        resource_type="baseline", resource_id=new_id,
        details={
            "old_baseline_id": str(bid),
            "agent_id": str(old_baseline.agent_id),
            "justification": req.justification,
            "scan_id": str(latest_scan.id),
        },
        ip_address=_client_ip(request),
    )

    await db.commit()

    return {
        "message": "New baseline created from latest scan — pending approval",
        "new_baseline_id": str(new_id),
        "old_baseline_status": old_status,
        "file_count": latest_scan.files_scanned,
    }


# ── Baseline Diff (Compare old vs new) ───────────────────────────────────

@router.get("/{baseline_id}/diff/{compare_id}")
async def diff_baselines(
    baseline_id: str,
    compare_id: str,
    db: AsyncSession = Depends(get_db),
    u=Depends(get_current_user)
):
    """Compare two baselines and return the differences."""
    try:
        bid1 = uuid.UUID(baseline_id)
        bid2 = uuid.UUID(compare_id)
    except ValueError:
        raise HTTPException(400, "Invalid baseline IDs")

    r1 = await db.execute(select(Baseline).where(Baseline.id == bid1))
    r2 = await db.execute(select(Baseline).where(Baseline.id == bid2))
    b1 = r1.scalar_one_or_none()
    b2 = r2.scalar_one_or_none()

    if not b1 or not b2:
        raise HTTPException(404, "Baseline(s) not found")

    files1 = {f["path"]: f for f in (b1.baseline_data or {}).get("files", [])}
    files2 = {f["path"]: f for f in (b2.baseline_data or {}).get("files", [])}

    added = []
    removed = []
    modified = []

    for path, f in files2.items():
        if path not in files1:
            added.append({"path": path, "new": f})
        elif files1[path].get("hash") != f.get("hash"):
            modified.append({"path": path, "old": files1[path], "new": f})

    for path, f in files1.items():
        if path not in files2:
            removed.append({"path": path, "old": f})

    return {
        "baseline_old": {"id": str(bid1), "file_count": len(files1), "created_at": b1.created_at.isoformat() if b1.created_at else None},
        "baseline_new": {"id": str(bid2), "file_count": len(files2), "created_at": b2.created_at.isoformat() if b2.created_at else None},
        "added": len(added),
        "removed": len(removed),
        "modified": len(modified),
        "changes": {
            "added": added[:100],      # Limit for API response size
            "removed": removed[:100],
            "modified": modified[:100],
        },
        "truncated": len(added) > 100 or len(removed) > 100 or len(modified) > 100,
    }


# ── View Baseline Details ─────────────────────────────────────────────────

@router.get("/{baseline_id}")
async def get_baseline_detail(
    baseline_id: str,
    db: AsyncSession = Depends(get_db),
    u=Depends(get_current_user)
):
    """Get baseline details including file count summary (not full data)."""
    try:
        bid = uuid.UUID(baseline_id)
    except ValueError:
        raise HTTPException(400, "Invalid baseline ID")

    result = await db.execute(text("""
        SELECT b.*, a.hostname as agent_hostname, u.username as approved_by_name
        FROM fim.baselines b
        LEFT JOIN fim.agents a ON b.agent_id = a.id
        LEFT JOIN fim.users u ON b.approved_by = u.id
        WHERE b.id = :id
    """), {"id": baseline_id})
    b = result.fetchone()

    if not b:
        raise HTTPException(404, "Baseline not found")

    files = (b.baseline_data or {}).get("files", [])

    return {
        "id": str(b.id),
        "agent_id": str(b.agent_id),
        "agent_hostname": b.agent_hostname or "unknown",
        "status": b.status,
        "is_active": b.is_active,
        "file_count": b.file_count or len(files),
        "checksum": b.checksum,
        "notes": b.notes,
        "created_at": b.created_at.isoformat() if b.created_at else None,
        "approved_at": b.approved_at.isoformat() if b.approved_at else None,
        "approved_by_name": b.approved_by_name,
        "sample_files": [f["path"] for f in files[:20]],
    }


# ── Delete Baseline ───────────────────────────────────────────────────────

@router.delete("/{baseline_id}")
async def delete_baseline(
    baseline_id: str,
    request: Request,
    db: AsyncSession = Depends(get_db),
    u=Depends(get_current_user)
):
    # Don't allow deleting active approved baselines
    result = await db.execute(text(
        "SELECT status, is_active FROM fim.baselines WHERE id = :id"
    ), {"id": baseline_id})
    b = result.fetchone()
    if not b:
        raise HTTPException(404, "Baseline not found")
    if b.is_active and b.status == "approved":
        raise HTTPException(400, "Cannot delete an active approved baseline. Re-baseline first.")

    await db.execute(text("DELETE FROM fim.baselines WHERE id = :id"), {"id": baseline_id})

    await AuditService.log(
        db, u.id, u.username, "DELETE_BASELINE",
        resource_type="baseline", resource_id=uuid.UUID(baseline_id),
        ip_address=_client_ip(request),
    )

    await db.commit()
    return {"message": "Deleted"}


# ── GAP #21: Baseline Version Control Endpoints ──────────────────

@router.get("/{baseline_id}/snapshot")
async def get_baseline_snapshot_info(
    baseline_id: str,
    db: AsyncSession = Depends(get_db),
    current_user=Depends(get_current_user)
):
    """GAP #21: Get git snapshot info for a specific baseline."""
    from sqlalchemy import text
    result = await db.execute(text("""
        SELECT b.id, b.git_hash, b.snapshot_path,
               b.approved_at, b.files_count, b.checksum,
               a.hostname
        FROM fim.baselines b
        JOIN fim.agents a ON b.agent_id = a.id
        WHERE b.id = :id
    """), {"id": baseline_id})
    row = result.fetchone()
    if not row:
        raise HTTPException(404, "Baseline not found")
    return {
        "baseline_id":   str(row.id),
        "git_hash":      row.git_hash,
        "snapshot_path": row.snapshot_path,
        "approved_at":   str(row.approved_at) if row.approved_at else None,
        "files_count":   row.files_count,
        "checksum":      row.checksum,
        "agent_hostname": row.hostname,
        "has_snapshot":  row.git_hash is not None,
    }


@router.get("/agent/{hostname}/history")
async def get_agent_baseline_history(
    hostname: str,
    db: AsyncSession = Depends(get_db),
    current_user=Depends(get_current_user)
):
    """GAP #21: Full version history for an agent's baselines."""
    history = await get_baseline_history(hostname)
    return {
        "agent_hostname": hostname,
        "history":        history,
        "total_snapshots": len(history),
    }


@router.get("/snapshot/{git_hash}")
async def get_snapshot_at_commit(
    git_hash: str,
    hostname: str,
    db: AsyncSession = Depends(get_db),
    current_user=Depends(get_current_user)
):
    """GAP #21: Retrieve baseline snapshot at a specific git commit."""
    snapshot = await get_snapshot_content(git_hash, hostname)
    if not snapshot:
        raise HTTPException(404, f"Snapshot not found for hash {git_hash}")
    return snapshot


@router.post("/backfill-snapshots")
async def backfill_baseline_snapshots(
    db: AsyncSession = Depends(get_db),
    current_user=Depends(get_current_user)
):
    """GAP #21: Admin-only: Create git snapshots for all existing baselines."""
    if current_user.role != "admin":
        raise HTTPException(403, "Admin only")
    count = await snapshot_all_approved_baselines(db)
    return {"message": f"Backfilled {count} baseline snapshot(s)"}

# ── End GAP #21 ──────────────────────────────────────────────────


# ── GAP #23: Baseline Diff Signing Endpoints ─────────────────────

@router.get("/{baseline_id}/diff/verify")
async def verify_baseline_diff(
    baseline_id: str,
    db: AsyncSession = Depends(get_db),
    current_user=Depends(get_current_user)
):
    """
    GAP #23: Verify the cryptographic signature of a baseline diff.
    Call this before approving any baseline to detect tampering.
    """
    from sqlalchemy import text
    from app.services.diff_signing import verify_diff_signature

    # Get stored diff and signature
    result = await db.execute(text("""
        SELECT id, diff_data, diff_signature, diff_generated_at,
               diff_sig_algorithm
        FROM fim.baselines
        WHERE id = :id
    """), {"id": baseline_id})
    row = result.fetchone()

    if not row:
        raise HTTPException(404, "Baseline not found")

    if not row.diff_signature:
        return {
            "baseline_id":    baseline_id,
            "signature_valid": None,
            "message": "No signature stored — diff was generated before GAP #23 fix",
            "recommendation": "Re-generate diff to create a signed version",
        }

    # Verify
    diff_data = row.diff_data or {}
    is_valid  = verify_diff_signature(diff_data, row.diff_signature, baseline_id)

    return {
        "baseline_id":       baseline_id,
        "signature_valid":   is_valid,
        "signature":         row.diff_signature[:16] + "...",
        "algorithm":         row.diff_sig_algorithm or "HMAC-SHA256",
        "diff_generated_at": str(row.diff_generated_at) if row.diff_generated_at else None,
        "warning": None if is_valid else (
            "⚠️ SECURITY ALERT: Diff signature invalid — possible tampering! "
            "Do NOT approve this baseline."
        ),
        "status": "✅ Diff integrity verified" if is_valid else "❌ TAMPERED",
    }


@router.get("/{baseline_id}/diff/signed")
async def get_signed_diff(
    baseline_id: str,
    db: AsyncSession = Depends(get_db),
    current_user=Depends(get_current_user)
):
    """
    GAP #23: Get baseline diff WITH signature verification result.
    Always use this endpoint for approval workflows.
    """
    from sqlalchemy import text
    from app.services.diff_signing import create_signed_diff_response

    result = await db.execute(text("""
        SELECT id, diff_data, diff_signature
        FROM fim.baselines WHERE id = :id
    """), {"id": baseline_id})
    row = result.fetchone()

    if not row:
        raise HTTPException(404, "Baseline not found")

    diff_data = row.diff_data or {}
    signature = row.diff_signature or ""

    return create_signed_diff_response(diff_data, baseline_id, signature)

# ── End GAP #23 ──────────────────────────────────────────────────

