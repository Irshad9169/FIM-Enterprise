from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, desc, text
from typing import List, Dict, Tuple, Set, Optional, Optional, List
from datetime import datetime, timedelta

from app.core.database import get_db
from app.core.security import get_current_user
from app.models.models import User, Alert

router = APIRouter()

@router.get("")
async def list_alerts(
    skip: int = 0,
    limit: int = 100,
    days: Optional[int] = Query(None, description="Filter alerts by last N days"),
    severity: Optional[str] = None,
    status: Optional[str] = None,
    agent_id: Optional[str] = None,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """List alerts with filtering"""
    
    query = select(Alert)
    
    # Filter by date range if days provided
    if days:
        cutoff_date = datetime.now() - timedelta(days=days)
        query = query.where(Alert.created_at >= cutoff_date)
        
    if severity:
        query = query.where(Alert.severity == severity)
        
    if status:
        query = query.where(Alert.status == status)
        
    if agent_id:
        query = query.where(Alert.agent_id == agent_id)
        
    query = query.order_by(desc(Alert.created_at)).offset(skip).limit(limit)
    
    result = await db.execute(query)
    alerts = result.scalars().all()
    
    return {"alerts": alerts, "total": len(alerts)}


@router.patch("/{alert_id}/acknowledge")
async def acknowledge_alert(
    alert_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Acknowledge an open alert"""
    import uuid as _uuid
    try:
        aid = _uuid.UUID(alert_id)
    except ValueError:
        raise HTTPException(400, "Invalid alert ID")

    result = await db.execute(select(Alert).where(Alert.id == aid))
    alert = result.scalar_one_or_none()
    if not alert:
        raise HTTPException(404, "Alert not found")
    if alert.status != "open":
        raise HTTPException(400, f"Alert is already {alert.status}")

    alert.status = "acknowledged"
    alert.assigned_to = current_user.id
    alert.resolution_notes = f"Acknowledged by {current_user.username} at {datetime.utcnow().isoformat()}"
    await db.commit()

    return {"success": True, "alert_id": alert_id, "status": "acknowledged"}


from pydantic import BaseModel
from typing import List, Dict, Tuple, Set, Optional, List as TList


class BulkAlertAction(BaseModel):
    alert_ids: TList[str]
    action: str  # 'acknowledge', 'resolve', 'false_positive'


@router.patch("/bulk")
async def bulk_alert_action(
    req: BulkAlertAction,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Bulk acknowledge, resolve, or mark alerts as false positive."""
    valid_actions = {"acknowledge": "acknowledged", "resolve": "resolved", "false_positive": "false_positive"}
    new_status = valid_actions.get(req.action)
    if not new_status:
        raise HTTPException(400, f"Invalid action. Use: {list(valid_actions.keys())}")

    if not req.alert_ids:
        raise HTTPException(400, "No alert IDs provided")

    # Update all matching alerts
    placeholders = ",".join(f"'{aid}'" for aid in req.alert_ids)
    result = await db.execute(text(f"""
        UPDATE fim.alerts
        SET status = :status, assigned_to = :uid,
            resolution_notes = COALESCE(resolution_notes, '') || :note
        WHERE id IN ({placeholders}) AND status = 'open'
        RETURNING id
    """), {
        "status": new_status,
        "uid": current_user.id,
        "note": f"\nBulk {req.action} by {current_user.username} at {datetime.utcnow().isoformat()}"
    })
    updated = result.fetchall()
    await db.commit()

    return {"updated": len(updated), "action": req.action, "new_status": new_status}
