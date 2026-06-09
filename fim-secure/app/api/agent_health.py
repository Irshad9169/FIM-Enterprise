"""
Agent Health Monitoring Endpoints
"""
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, text
import uuid

from app.core.database import get_db
from app.core.security import get_current_user
from app.models import User
from app.services.agent_health import AgentHealthMonitor

router = APIRouter()

@router.get("/summary")
async def get_health_summary(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Get overall agent health summary"""
    summary = await AgentHealthMonitor.get_health_summary(db)
    return summary

@router.get("/agent/{agent_id}")
async def get_agent_health(
    agent_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Get health status for a specific agent"""
    try:
        agent_uuid = uuid.UUID(agent_id)
    except ValueError:
        raise HTTPException(400, "Invalid agent ID")
    
    health = await AgentHealthMonitor.check_agent_health(agent_uuid, db)
    
    if 'error' in health:
        raise HTTPException(404, health['error'])
    
    return health

@router.get("/stale")
async def get_stale_agents(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Get list of agents that haven't reported recently"""
    stale = await AgentHealthMonitor.get_stale_agents(db)
    return {
        'stale_agents': stale,
        'count': len(stale)
    }

@router.post("/check")
async def run_health_check(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Manually trigger health check for all agents"""
    result = await AgentHealthMonitor.update_agent_health_status(db)
    return {
        'success': True,
        'message': 'Health check complete',
        **result
    }

@router.get("/events/{agent_id}")
async def get_agent_health_events(
    agent_id: str,
    limit: int = 50,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Get health event history for an agent"""
    try:
        agent_uuid = uuid.UUID(agent_id)
    except ValueError:
        raise HTTPException(400, "Invalid agent ID")
    
    result = await db.execute(
        text("""
            SELECT event_type, previous_status, new_status, details, created_at
            FROM fim.agent_health_events
            WHERE agent_id = :agent_id
            ORDER BY created_at DESC
            LIMIT :limit
        """),
        {'agent_id': str(agent_uuid), 'limit': limit}
    )
    
    events = result.fetchall()
    
    return {
        'agent_id': agent_id,
        'events': [
            {
                'event_type': e[0],
                'previous_status': e[1],
                'new_status': e[2],
                'details': e[3],
                'timestamp': e[4].isoformat() if e[4] else None
            }
            for e in events
        ],
        'total': len(events)
    }
