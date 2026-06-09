"""
Alert Action Endpoints - Acknowledge, Resolve, Comment
"""
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, update, func, case
from pydantic import BaseModel
from typing import Optional
import uuid
from datetime import datetime

from app.core.database import get_db
from app.core.security import get_current_user
from app.models import User
from app.models.models import Alert

router = APIRouter()

class AlertAcknowledgeRequest(BaseModel):
    alert_id: str
    notes: Optional[str] = None

class AlertResolveRequest(BaseModel):
    alert_id: str
    resolution_notes: str

class BulkAcknowledgeRequest(BaseModel):
    alert_ids: list[str]
    notes: Optional[str] = None

@router.post("/acknowledge")
async def acknowledge_alert(
    request: AlertAcknowledgeRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Mark alert as acknowledged"""
    try:
        alert_id = uuid.UUID(request.alert_id)
    except ValueError:
        raise HTTPException(400, "Invalid alert ID")

    result = await db.execute(select(Alert).where(Alert.id == alert_id))
    alert = result.scalar_one_or_none()
    
    if not alert:
        raise HTTPException(404, "Alert not found")
    
    if alert.status == 'resolved':
        raise HTTPException(400, "Cannot acknowledge resolved alert")

    alert.status = 'acknowledged'
    alert.acknowledged_at = datetime.utcnow()
    alert.assigned_to = current_user.id
    alert.acknowledged_by = current_user.id
    
    if request.notes:
        existing_notes = alert.resolution_notes or ""
        alert.resolution_notes = f"{existing_notes}\n[{datetime.utcnow().isoformat()}] Acknowledged by {current_user.username}: {request.notes}"

    await db.commit()
    await db.refresh(alert)

    return {
        "success": True,
        "alert_id": str(alert.id),
        "status": alert.status,
        "acknowledged_at": alert.acknowledged_at.isoformat()
    }

@router.post("/acknowledge/bulk")
async def bulk_acknowledge(
    request: BulkAcknowledgeRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Acknowledge multiple alerts at once"""
    alert_uuids = []
    for aid in request.alert_ids:
        try:
            alert_uuids.append(uuid.UUID(aid))
        except ValueError:
            continue
    
    if not alert_uuids:
        raise HTTPException(400, "No valid alert IDs provided")

    notes = f"Bulk acknowledged by {current_user.username}"
    if request.notes:
        notes += f": {request.notes}"

    result = await db.execute(
        update(Alert)
        .where(Alert.id.in_(alert_uuids))
        .where(Alert.status == 'open')
        .values(
            status='acknowledged',
            acknowledged_at=datetime.utcnow(),
            assigned_to=current_user.id,
            acknowledged_by=current_user.id,
            resolution_notes=notes
        )
    )
    
    await db.commit()
    
    return {
        "success": True,
        "acknowledged_count": result.rowcount
    }

@router.post("/resolve")
async def resolve_alert(
    request: AlertResolveRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Mark alert as resolved"""
    try:
        alert_id = uuid.UUID(request.alert_id)
    except ValueError:
        raise HTTPException(400, "Invalid alert ID")

    result = await db.execute(select(Alert).where(Alert.id == alert_id))
    alert = result.scalar_one_or_none()
    
    if not alert:
        raise HTTPException(404, "Alert not found")

    alert.status = 'resolved'
    alert.resolved_at = datetime.utcnow()
    alert.assigned_to = current_user.id
    
    existing_notes = alert.resolution_notes or ""
    alert.resolution_notes = f"{existing_notes}\n[{datetime.utcnow().isoformat()}] Resolved by {current_user.username}: {request.resolution_notes}"

    await db.commit()

    return {
        "success": True,
        "alert_id": str(alert.id),
        "status": alert.status
    }

@router.get("/stats")
async def get_alert_stats(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Get alert statistics"""
    result = await db.execute(
        select(
            func.count(Alert.id).label('total'),
            func.sum(case((Alert.status == 'open', 1), else_=0)).label('open'),
            func.sum(case((Alert.status == 'acknowledged', 1), else_=0)).label('acknowledged'),
            func.sum(case((Alert.status == 'resolved', 1), else_=0)).label('resolved'),
            func.sum(case((Alert.severity == 'critical', 1), else_=0)).label('critical'),
            func.sum(case((Alert.severity == 'high', 1), else_=0)).label('high'),
            func.sum(case((Alert.severity == 'medium', 1), else_=0)).label('medium'),
            func.sum(case((Alert.severity == 'low', 1), else_=0)).label('low')
        )
    )
    
    stats = result.one()
    
    return {
        "total_alerts": int(stats.total or 0),
        "by_status": {
            "open": int(stats.open or 0),
            "acknowledged": int(stats.acknowledged or 0),
            "resolved": int(stats.resolved or 0)
        },
        "by_severity": {
            "critical": int(stats.critical or 0),
            "high": int(stats.high or 0),
            "medium": int(stats.medium or 0),
            "low": int(stats.low or 0)
        }
    }
