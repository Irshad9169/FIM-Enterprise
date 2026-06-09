"""
Scan Request Management API
Manual scan triggers for agents
"""
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, update, desc
from datetime import datetime, timedelta
from typing import Optional
import uuid

from app.core.database import get_db
from app.core.rbac import require_role
from app.models import User, Agent, ScanRequest, Scan

router = APIRouter()

@router.post("/trigger/{agent_id}")
async def trigger_scan(
    agent_id: str,
    force: bool = Query(False, description="Force scan even if recently scanned"),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_role(['admin', 'analyst']))
):
    """
    Trigger a manual scan for an agent
    By default, only if last scan was > 24 hours ago
    Use ?force=true to bypass cooldown
    """
    try:
        agent_uuid = uuid.UUID(agent_id)
    except ValueError:
        raise HTTPException(400, "Invalid agent ID")

    # Get agent
    result = await db.execute(
        select(Agent).where(Agent.id == agent_uuid)
    )
    agent = result.scalar_one_or_none()

    if not agent:
        raise HTTPException(404, "Agent not found")

    # Get last scan (only if not forcing)
    if not force:
        result = await db.execute(
            select(Scan)
            .where(Scan.agent_id == agent_uuid)
            .order_by(desc(Scan.completed_at))
            .limit(1)
        )
        last_scan = result.scalar_one_or_none()

        # Check if scan is needed
        if last_scan and last_scan.completed_at:
            hours_since_scan = (datetime.utcnow() - last_scan.completed_at).total_seconds() / 3600
            if hours_since_scan < 1:  # Changed from 24 to 1 hour
                raise HTTPException(
                    400,
                    f"Agent scanned {hours_since_scan:.1f} hours ago. Wait {1 - hours_since_scan:.1f} more hours or use ?force=true"
                )

    # Check if there's already a pending request
    result = await db.execute(
        select(ScanRequest)
        .where(ScanRequest.agent_id == agent_uuid)
        .where(ScanRequest.status.in_(['pending', 'acknowledged']))
    )
    existing_request = result.scalar_one_or_none()

    if existing_request:
        raise HTTPException(400, "Scan request already pending for this agent")

    # Create scan request
    scan_request = ScanRequest(
        id=uuid.uuid4(),
        agent_id=agent_uuid,
        requested_by=current_user.id,
        status='pending',
        requested_at=datetime.utcnow(),
        timeout_at=datetime.utcnow() + timedelta(hours=1)
    )

    db.add(scan_request)

    # Simple audit log
    try:
        from app.models import AuditLog
        audit = AuditLog(
            id=uuid.uuid4(),
            user_id=current_user.id,
            username=current_user.username,
            action='scan_triggered' if not force else 'scan_forced',
            resource_type='agent',
            resource_id=agent_uuid,
            details={'agent_hostname': agent.hostname, 'force': force},
            timestamp=datetime.utcnow()
        )
        db.add(audit)
    except Exception:
        pass

    await db.commit()

    return {
        'success': True,
        'request_id': str(scan_request.id),
        'agent_id': agent_id,
        'agent_hostname': agent.hostname,
        'message': 'Scan request created. Agent will execute on next heartbeat.',
        'status': 'pending',
        'forced': force
    }

@router.get("/pending/{agent_id}")
async def get_pending_scan_requests(
    agent_id: str,
    db: AsyncSession = Depends(get_db)
):
    """
    Get pending scan requests for an agent
    Called by agent during heartbeat
    """
    try:
        agent_uuid = uuid.UUID(agent_id)
    except ValueError:
        raise HTTPException(400, "Invalid agent ID")

    result = await db.execute(
        select(ScanRequest)
        .where(ScanRequest.agent_id == agent_uuid)
        .where(ScanRequest.status == 'pending')
        .where(ScanRequest.timeout_at > datetime.utcnow())
        .order_by(ScanRequest.requested_at)
    )
    requests = result.scalars().all()

    # Mark as acknowledged
    for req in requests:
        req.status = 'acknowledged'
        req.acknowledged_at = datetime.utcnow()

    await db.commit()

    return {
        'pending_scans': len(requests),
        'requests': [
            {
                'request_id': str(req.id),
                'requested_at': req.requested_at.isoformat()
            }
            for req in requests
        ]
    }

@router.put("/complete/{request_id}")
async def complete_scan_request(
    request_id: str,
    scan_id: Optional[str] = None,
    error_message: Optional[str] = None,
    db: AsyncSession = Depends(get_db)
):
    """Mark scan request as completed"""
    try:
        request_uuid = uuid.UUID(request_id)
    except ValueError:
        raise HTTPException(400, "Invalid request ID")

    result = await db.execute(
        select(ScanRequest).where(ScanRequest.id == request_uuid)
    )
    scan_request = result.scalar_one_or_none()

    if not scan_request:
        raise HTTPException(404, "Scan request not found")

    if error_message:
        scan_request.status = 'failed'
        scan_request.error_message = error_message
    else:
        scan_request.status = 'completed'
        if scan_id:
            scan_request.scan_id = uuid.UUID(scan_id)

    scan_request.completed_at = datetime.utcnow()

    if not error_message and scan_id:
        try:
            await db.execute(
                update(Agent)
                .where(Agent.id == scan_request.agent_id)
                .values(last_scan_at=datetime.utcnow())
            )
        except Exception:
            pass

    await db.commit()

    return {
        'success': True,
        'request_id': request_id,
        'status': scan_request.status
    }

@router.get("/status/{agent_id}")
async def get_scan_request_status(
    agent_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_role(['admin', 'analyst', 'trainee', 'auditor']))
):
    """Get scan request status for an agent"""
    try:
        agent_uuid = uuid.UUID(agent_id)
    except ValueError:
        raise HTTPException(400, "Invalid agent ID")

    result = await db.execute(
        select(ScanRequest)
        .where(ScanRequest.agent_id == agent_uuid)
        .order_by(desc(ScanRequest.requested_at))
        .limit(5)
    )
    requests = result.scalars().all()

    return {
        'agent_id': agent_id,
        'requests': [
            {
                'request_id': str(req.id),
                'status': req.status,
                'requested_at': req.requested_at.isoformat() if req.requested_at else None,
                'acknowledged_at': req.acknowledged_at.isoformat() if req.acknowledged_at else None,
                'completed_at': req.completed_at.isoformat() if req.completed_at else None,
                'error_message': req.error_message
            }
            for req in requests
        ]
    }

@router.post("/cleanup")
async def cleanup_expired_requests(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_role(['admin']))
):
    """Clean up expired scan requests"""
    result = await db.execute(
        update(ScanRequest)
        .where(ScanRequest.status.in_(['pending', 'acknowledged']))
        .where(ScanRequest.timeout_at < datetime.utcnow())
        .values(status='timeout', completed_at=datetime.utcnow())
    )

    await db.commit()

    return {
        'success': True,
        'expired_requests': result.rowcount
    }
