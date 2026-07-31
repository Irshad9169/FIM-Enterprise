"""
Scan Results Endpoints
"""
from fastapi import APIRouter, Depends, HTTPException, Query, Request
from datetime import datetime, timezone
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, desc, text
from pydantic import BaseModel
from typing import List, Dict, Tuple, Set, Optional, List, Optional, Dict
import uuid
import json
import logging

from app.core.database import get_db
from app.core.agent_auth import check_agent_key
from app.models.models import Agent, Scan
from app.services.change_detector import ChangeDetector

logger = logging.getLogger(__name__)
router = APIRouter()

class ScanSubmitRequest(BaseModel):
    agent_id: str
    timestamp: str
    files: List[Dict]
    total_files: int
    scan_type: Optional[str] = "full"  # e.g. "full" (scheduled) vs "realtime" (event-triggered)

@router.post("/submit")
async def submit_scan(raw_request: Request, db: AsyncSession = Depends(get_db)):
    # GAP #11: enforce payload size and file count limits
    body_bytes = await raw_request.body()
    if len(body_bytes) > 50000000:
        raise HTTPException(
            status_code=413,
            detail="Scan payload too large (max 50 MB)"
        )
    try:
        scan_data = json.loads(body_bytes)
    except json.JSONDecodeError:
        raise HTTPException(status_code=400, detail="Invalid JSON payload")
    # 200,000 gives headroom above real observed scans (test06 legitimately
    # scans 108k+ files under /opt) while keeping typical payloads
    # comfortably under the 50MB cap above — don't raise this much further
    # without also reconsidering that relationship.
    if len(scan_data.get("files", [])) > 200000:
        raise HTTPException(
            status_code=400,
            detail="Too many files in scan (max 200,000)"
        )
    # Parse body
    try:
        raw_body = await raw_request.body()
        body = json.loads(raw_body)
        request = ScanSubmitRequest(**body)
    except Exception as e:
        raise HTTPException(400, f"Invalid request body: {e}")

    try:
        agent_uuid = uuid.UUID(request.agent_id)
    except ValueError:
        raise HTTPException(400, "Invalid agent ID")

    result = await db.execute(select(Agent).where(Agent.id == agent_uuid))
    agent = result.scalar_one_or_none()
    if not agent: raise HTTPException(404, "Agent not found")

    # Real per-agent key check — this used to "verify" an HMAC signature
    # computed from the X-API-Key header of this SAME request (a
    # self-consistency check, not authentication; any caller could invent
    # their own key and sign with it). Now looks up the agent's actual
    # established key (see app/core/agent_auth.py) instead.
    if not check_agent_key(agent, raw_request.headers.get("x-api-key", "")):
        raise HTTPException(403, "Invalid or missing API key")
    await db.commit()

    try:
        timestamp_str = request.timestamp.replace('Z', '+00:00')
        dt_parsed = datetime.fromisoformat(timestamp_str)
        # The agent sends datetime.utcnow().isoformat() -- a naive string
        # with no offset, but semantically already UTC. datetime.astimezone()
        # on a naive value assumes it's in the *server's local* timezone
        # first, then converts -- silently mis-shifting an already-UTC value
        # by the server's UTC offset (e.g. ~5:30 for IST). Attach UTC
        # explicitly for naive input instead of letting astimezone guess.
        if dt_parsed.tzinfo is None:
            dt_parsed = dt_parsed.replace(tzinfo=timezone.utc)
        dt_utc = dt_parsed.astimezone(timezone.utc).replace(tzinfo=None)
    except Exception: dt_utc = datetime.utcnow()

    scan = Scan(
        id=uuid.uuid4(),
        agent_id=agent_uuid,
        scan_type=request.scan_type or "full",
        status="completed",
        files_scanned=request.total_files,
        files_changed=0,
        scan_duration=0,
        scan_data={"files": request.files},
        started_at=dt_utc,
        completed_at=datetime.utcnow()
    )
    db.add(scan)
    await db.commit()
    await db.refresh(scan)

    change_stats = {}
    try:
        change_stats = await ChangeDetector.process_scan(scan.id, db)
        scan.files_changed = change_stats.get('changes_detected', 0)
        await db.commit()
    except Exception as e:
        change_stats = {'error': str(e)}

    return {"success": True, "scan_id": str(scan.id), "change_detection": change_stats}

@router.get("")
async def list_scans(
    search: Optional[str] = None,
    limit: int = 100,
    db: AsyncSession = Depends(get_db)
):
    """List latest scan for each agent"""
    try:
        # Get latest scan per agent using subquery
        query_sql = """
            SELECT s.id, s.agent_id, s.scan_type, s.status, s.files_scanned,
                   s.files_changed, s.started_at, s.completed_at, a.hostname
            FROM fim.scans s
            JOIN fim.agents a ON s.agent_id = a.id
            WHERE a.status != 'inactive'
            AND s.id IN (
                SELECT DISTINCT ON (agent_id) id 
                FROM fim.scans 
                ORDER BY agent_id, started_at DESC
            )
        """
        params = {}
        if search:
            query_sql += " AND a.hostname ILIKE :search"
            params['search'] = f"%{search}%"
        
        result = await db.execute(text(query_sql), params)
        rows = result.fetchall()
        scans = rows[:limit]
        
        # Calculate scan health for each scan
        from datetime import datetime as dt, timezone
        now = dt.now(timezone.utc)
        
        scans_with_health = []
        for r in scans:
            hours_since = None
            if not r.started_at:
                scan_health = "never_scanned"
            else:
                hours_since = (now - r.started_at).total_seconds() / 3600
                if hours_since < 24:
                    scan_health = "healthy"
                elif hours_since < 48:
                    scan_health = "stale"
                elif hours_since < 72:
                    scan_health = "warning"
                else:
                    scan_health = "critical"

            scans_with_health.append({
                "id": str(r.id),
                "agent_id": str(r.agent_id),
                "agent_hostname": r.hostname,
                "scan_type": r.scan_type,
                "status": r.status,
                "files_scanned": r.files_scanned,
                "files_changed": r.files_changed,
                "started_at": str(r.started_at),
                "completed_at": str(r.completed_at),
                "scan_health": scan_health,
                # Frontend's Age column (ScansPage.tsx) reads this directly —
                # was never actually sent, so Age was always blank.
                "hours_since_scan": round(hours_since, 1) if hours_since is not None else None,
            })
        
        # Calculate summary counts
        summary = {
            "healthy": sum(1 for s in scans_with_health if s["scan_health"] == "healthy"),
            "stale": sum(1 for s in scans_with_health if s["scan_health"] == "stale"),
            "warning": sum(1 for s in scans_with_health if s["scan_health"] == "warning"),
            "critical": sum(1 for s in scans_with_health if s["scan_health"] == "critical"),
            "never_scanned": sum(1 for s in scans_with_health if s["scan_health"] == "never_scanned"),
            "total": len(scans_with_health)
        }
        
        return {
            "scans": scans_with_health,
            "summary": summary
        }
    except Exception as e:
        logger.error(f"List scans error: {e}")
        return {"scans": [], "total": 0}
@router.get("/{scan_id}")
async def get_scan(scan_id: str, db: AsyncSession = Depends(get_db)):
    # ... (Keep existing get_scan) ...
    try:
        result = await db.execute(select(Scan).where(Scan.id == uuid.UUID(scan_id)))
        scan = result.scalar_one_or_none()
        if not scan: raise HTTPException(404, "Not found")
        return {
            "id": str(scan.id),
            "agent_id": str(scan.agent_id),
            "scan_type": scan.scan_type,
            "status": scan.status,
            "files_scanned": scan.files_scanned,
            "files_changed": scan.files_changed,
            "started_at": str(scan.started_at),
            "completed_at": str(scan.completed_at),
            "scan_data": scan.scan_data
        }
    except: raise HTTPException(404, "Not found")
