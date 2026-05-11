"""
Enhanced Agent Management API
Search, recently scanned, scan status
"""
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, desc, func
from datetime import datetime
from typing import Optional
import uuid

from app.core.database import get_db
from app.core.rbac import require_role
from app.models import User, Agent, Scan

router = APIRouter()

@router.get("/search")
async def search_agents(
    query: str = Query(..., min_length=2),
    limit: int = Query(10, le=50),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_role(['admin', 'analyst', 'trainee', 'auditor']))
):
    """
    Search agents by hostname (FQDN)
    Returns agents with last scan info
    """
    # Build search query
    search_pattern = f"%{query}%"
    
    result = await db.execute(
        select(Agent, func.max(Scan.completed_at).label('last_scan'))
        .outerjoin(Scan, Scan.agent_id == Agent.id)
        .where(Agent.hostname.ilike(search_pattern))
        .group_by(Agent.id)
        .order_by(Agent.hostname)
        .limit(limit)
    )
    
    agents_data = result.all()
    
    agents = []
    for agent, last_scan in agents_data:
        # Calculate if scan is needed
        scan_needed = False
        hours_since_scan = None
        
        if last_scan:
            hours_since_scan = (datetime.utcnow() - last_scan).total_seconds() / 3600
            scan_needed = hours_since_scan > 24
        else:
            scan_needed = True
        
        # Get scan_count safely
        scan_count = 0
        try:
            scan_count = agent.scan_count or 0
        except AttributeError:
            scan_count = 0
        
        agents.append({
            'id': str(agent.id),
            'hostname': agent.hostname,
            'ip_address': agent.ip_address,
            'status': agent.status,
            'last_heartbeat': agent.last_heartbeat.isoformat() if agent.last_heartbeat else None,
            'last_scan_at': last_scan.isoformat() if last_scan else None,
            'hours_since_scan': round(hours_since_scan, 1) if hours_since_scan else None,
            'scan_needed': scan_needed,
            'scan_count': scan_count
        })
    
    return {
        'query': query,
        'results': agents,
        'count': len(agents)
    }

@router.get("/recently-scanned")
async def get_recently_scanned_agents(
    limit: int = Query(10, le=50),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_role(['admin', 'analyst', 'trainee', 'auditor']))
):
    """
    Get agents that were recently scanned
    Ordered by last scan time (most recent first)
    """
    # Get agents with recent scans
    result = await db.execute(
        select(Agent, func.max(Scan.completed_at).label('last_scan'))
        .join(Scan, Scan.agent_id == Agent.id)
        .where(Scan.status == 'completed')
        .group_by(Agent.id)
        .order_by(desc('last_scan'))
        .limit(limit)
    )
    
    agents_data = result.all()
    
    agents = []
    for agent, last_scan in agents_data:
        hours_since_scan = (datetime.utcnow() - last_scan).total_seconds() / 3600 if last_scan else None
        
        # Get scan_count safely
        scan_count = 0
        try:
            scan_count = agent.scan_count or 0
        except AttributeError:
            scan_count = 0
        
        agents.append({
            'id': str(agent.id),
            'hostname': agent.hostname,
            'ip_address': agent.ip_address,
            'status': agent.status,
            'last_scan_at': last_scan.isoformat() if last_scan else None,
            'hours_since_scan': round(hours_since_scan, 1) if hours_since_scan else None,
            'scan_count': scan_count,
            'is_healthy': agent.is_healthy
        })
    
    return {
        'recently_scanned': agents,
        'count': len(agents)
    }

@router.get("/scan-status/{agent_id}")
async def get_agent_scan_status(
    agent_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_role(['admin', 'analyst', 'trainee', 'auditor']))
):
    """
    Get detailed scan status for an agent
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
    
    # Get last scan
    result = await db.execute(
        select(Scan)
        .where(Scan.agent_id == agent_uuid)
        .order_by(desc(Scan.completed_at))
        .limit(1)
    )
    last_scan = result.scalar_one_or_none()
    
    # Calculate scan status
    scan_needed = False
    hours_since_scan = None
    
    if last_scan and last_scan.completed_at:
        hours_since_scan = (datetime.utcnow() - last_scan.completed_at).total_seconds() / 3600
        scan_needed = hours_since_scan > 24
    else:
        scan_needed = True
    
    # Get scan_count safely
    scan_count = 0
    try:
        scan_count = agent.scan_count or 0
    except AttributeError:
        scan_count = 0
    
    return {
        'agent_id': agent_id,
        'hostname': agent.hostname,
        'last_scan_at': last_scan.completed_at.isoformat() if last_scan and last_scan.completed_at else None,
        'hours_since_scan': round(hours_since_scan, 1) if hours_since_scan else None,
        'scan_needed': scan_needed,
        'total_scans': scan_count,
        'last_scan_status': last_scan.status if last_scan else None,
        'last_scan_files': last_scan.files_scanned if last_scan else None
    }
