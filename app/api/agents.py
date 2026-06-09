from app.core.rbac import analyst_plus
from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, desc, text
from pydantic import BaseModel
from typing import Optional
from datetime import datetime
import uuid

from app.core.database import get_db
from app.core.security import get_current_user
from app.models.models import User, Agent, ScanRequest

router = APIRouter()

class AgentRegisterRequest(BaseModel):
    hostname: str
    ip_address: Optional[str] = None
    os_type: Optional[str] = None
    os_version: Optional[str] = None
    agent_version: Optional[str] = None
    tags: Optional[dict] = None

class AgentHeartbeatRequest(BaseModel):
    agent_id: str
    hostname: str
    timestamp: Optional[str] = None

@router.get("")
async def list_agents(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """List all registered agents"""
    result = await db.execute(select(Agent).where(Agent.status != 'inactive').order_by(Agent.hostname))
    agents = result.scalars().all()
    return {"agents": agents}

@router.post("/register")
async def register_agent(
    request: AgentRegisterRequest,
    db: AsyncSession = Depends(get_db)
):
    """Register a new agent"""
    result = await db.execute(select(Agent).where(Agent.hostname == request.hostname))
    agent = result.scalar_one_or_none()
    
    if agent:
        agent.ip_address = request.ip_address
        agent.os_type = request.os_type
        agent.os_version = request.os_version
        agent.agent_version = request.agent_version
        agent.last_heartbeat = datetime.now()
        agent.status = 'online'
        if request.tags:
            agent.tags = request.tags
    else:
        agent = Agent(
            id=uuid.uuid4(),
            hostname=request.hostname,
            ip_address=request.ip_address,
            os_type=request.os_type,
            os_version=request.os_version,
            agent_version=request.agent_version,
            status='online',
            last_heartbeat=datetime.now(),
            tags=request.tags or {}
        )
        db.add(agent)
    
    await db.commit()
    return {"agent_id": str(agent.id), "status": "registered"}

@router.post("/heartbeat")
async def agent_heartbeat(
    request: AgentHeartbeatRequest,
    db: AsyncSession = Depends(get_db)
):
    """Process agent heartbeat and check for commands"""
    try:
        agent_uuid = uuid.UUID(request.agent_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid agent ID")
        
    result = await db.execute(select(Agent).where(Agent.id == agent_uuid))
    agent = result.scalar_one_or_none()
    
    if not agent:
        raise HTTPException(status_code=404, detail="Agent not found")
    
    # Update heartbeat
    agent.last_heartbeat = datetime.now()
    agent.status = 'online'
    agent.is_healthy = True
    
    # Check for pending scan requests
    scan_result = await db.execute(
        text("""
            SELECT id FROM fim.scan_requests 
            WHERE agent_id = :agent_id AND status = 'pending'
            LIMIT 1
        """),
        {"agent_id": str(agent_uuid)}
    )
    pending_scan = scan_result.fetchone()
    
    scan_required = False
    scan_id = None
    
    if pending_scan:
        scan_required = True
        scan_id = str(pending_scan.id)
        
        # Mark scan as in_progress
        await db.execute(
            text("UPDATE fim.scan_requests SET status = 'acknowledged', started_at = NOW() WHERE id = :id"),
            {"id": scan_id}
        )
    
    await db.commit()
    
    return {
        "status": "ok",
        "scan_required": scan_required,
        "scan_id": scan_id,
        "message": "Heartbeat received"
    }

@router.post("/{agent_id}/scan")
async def trigger_agent_scan(
    agent_id: str,
    force: bool = False,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Trigger an on-demand scan for a specific agent"""
    try:
        agent_uuid = uuid.UUID(agent_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid agent ID")
    
    result = await db.execute(
        text("SELECT id, hostname, last_scan_at FROM fim.agents WHERE id = :id"),
        {"id": str(agent_uuid)}
    )
    agent = result.fetchone()
    
    if not agent:
        raise HTTPException(status_code=404, detail="Agent not found")
    
    # Create scan request
    scan_request = ScanRequest(
        id=uuid.uuid4(),
        agent_id=agent_uuid,
        requested_by=current_user.id,
        status='pending'
    )
    
    db.add(scan_request)
    await db.commit()
    
    return {
        "message": f"Scan triggered for {agent.hostname}",
        "agent_id": agent_id,
        "forced": force
    }



class UpdateAgentTags(BaseModel):
    tags: list


@router.patch("/{agent_id}/tags")
async def update_agent_tags(
    agent_id: str, req: UpdateAgentTags,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Update agent tags/groups (e.g., ['production', 'web-tier'])."""
    import json as _json
    await db.execute(text(
        "UPDATE fim.agents SET tags = :tags WHERE id = :id"
    ), {"tags": _json.dumps(req.tags), "id": agent_id})
    await db.commit()
    return {"message": "Tags updated", "tags": req.tags}


@router.get("/groups")
async def list_agent_groups(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """List all unique agent tags/groups."""
    result = await db.execute(text("""
        SELECT DISTINCT jsonb_array_elements_text(tags) as tag
        FROM fim.agents WHERE tags IS NOT NULL AND tags != 'null'::jsonb
        ORDER BY tag
    """))
    return {"groups": [row.tag for row in result.fetchall()]}
