from app.core.rbac import analyst_plus
from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, desc, text
from pydantic import BaseModel
from typing import Optional, List
from datetime import datetime
import uuid

from app.core.database import get_db
from app.core.security import get_current_user
from app.services.audit_service import AuditService
from app.models.models import User, Agent, ScanRequest

router = APIRouter()


def _client_ip(request: Request) -> str:
    """Extract client IP from request, respecting X-Forwarded-For (mirrors app/api/reports.py's helper)."""
    forwarded = request.headers.get("x-forwarded-for")
    if forwarded:
        return forwarded.split(",")[0].strip()
    return request.client.host if request.client else ""

class AgentRegisterRequest(BaseModel):
    hostname: str
    ip_address: Optional[str] = None
    os_type: Optional[str] = None
    os_version: Optional[str] = None
    agent_version: Optional[str] = None
    tags: Optional[dict] = None
    script_hash: Optional[str] = None
    current_config: Optional[dict] = None

class AgentHeartbeatRequest(BaseModel):
    agent_id: str
    hostname: str
    timestamp: Optional[str] = None
    script_hash: Optional[str] = None
    current_config: Optional[dict] = None

class AgentConfigPathEntry(BaseModel):
    path: str
    exclude_patterns: List[str] = []

class AgentConfigPushRequest(BaseModel):
    paths: List[AgentConfigPathEntry]

class AgentConfigAckRequest(BaseModel):
    version: int

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
        # Trust-on-first-registration: only set if not already established —
        # re-registering an existing agent must not silently reset the
        # known-good hash (that would defeat the whole point).
        if request.script_hash and not agent.binary_hash:
            agent.binary_hash = request.script_hash
        if request.current_config:
            agent.reported_config = request.current_config
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
            tags=request.tags or {},
            binary_hash=request.script_hash,
            reported_config=request.current_config,
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
    if request.current_config:
        agent.reported_config = request.current_config

    # Self-integrity: seed the trust-on-first-sight baseline here too, not
    # just in register_agent() — an agent that already had a saved agent_id
    # before this feature existed will never call /register again, so
    # register_agent()'s seeding alone would leave binary_hash permanently
    # null for every pre-existing agent.
    if request.script_hash and not agent.binary_hash:
        agent.binary_hash = request.script_hash

    # Alert once per NEW mismatch (binary_hash_mismatch_since gates it), not
    # every heartbeat while it stays mismatched — mirrors the transition-based
    # approach used for stale-agent alerting.
    elif request.script_hash and agent.binary_hash and request.script_hash != agent.binary_hash:
        agent.pending_binary_hash = request.script_hash
        if agent.binary_hash_mismatch_since is None:
            agent.binary_hash_mismatch_since = datetime.utcnow()
            try:
                from app.services.email_service import EmailService
                recipients_res = await db.execute(text(
                    "SELECT email FROM fim.users WHERE role IN ('admin', 'analyst') AND is_active = true"
                ))
                recipients = [row.email for row in recipients_res.fetchall() if row.email]
                if recipients:
                    EmailService.notify_critical_alert(
                        agent.hostname, "agent/fim_agent.py", "agent_binary_hash_mismatch", recipients
                    )
            except Exception:
                pass  # never let a notification failure affect heartbeat processing

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
        # Item 11: agent compares this to its own last-applied version (kept
        # in its agent_config.yaml) and fetches new config only if newer —
        # same shape as scan_required's "act now" signal, not a new channel.
        "config_version": agent.desired_config_version,
        "message": "Heartbeat received"
    }

@router.post("/{agent_id}/accept-binary-hash")
async def accept_agent_binary_hash(
    agent_id: str,
    http_request: Request,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(analyst_plus)
):
    """
    Accept the agent's currently-reported script hash as the new known-good
    baseline — used after reviewing a legitimate agent code update that
    triggered a self-integrity mismatch alert.
    """
    try:
        agent_uuid = uuid.UUID(agent_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid agent ID")

    result = await db.execute(select(Agent).where(Agent.id == agent_uuid))
    agent = result.scalar_one_or_none()
    if not agent:
        raise HTTPException(status_code=404, detail="Agent not found")

    if not agent.binary_hash_mismatch_since or not agent.pending_binary_hash:
        raise HTTPException(status_code=400, detail="No pending binary hash mismatch for this agent")

    old_hash = agent.binary_hash
    accepted_hash = agent.pending_binary_hash
    agent.binary_hash = accepted_hash
    agent.pending_binary_hash = None
    agent.binary_hash_mismatch_since = None
    await db.commit()

    await AuditService.log(
        db, current_user.id, current_user.username, "AGENT_BINARY_HASH_ACCEPTED",
        resource_type="agent", resource_id=agent.id,
        details={"hostname": agent.hostname, "old_hash": old_hash, "accepted_hash": accepted_hash},
        ip_address=_client_ip(http_request),
    )
    await db.commit()

    return {"message": "Binary hash accepted as new baseline", "binary_hash": accepted_hash}


@router.put("/{agent_id}/config")
async def push_agent_config(
    agent_id: str,
    body: AgentConfigPushRequest,
    http_request: Request,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(analyst_plus)
):
    """
    Push a new monitored-paths config to an agent. Doesn't touch the agent
    directly — the agent picks this up on its next heartbeat (config_version
    field) and pulls it via GET .../config, same pattern as scan_required.
    """
    try:
        agent_uuid = uuid.UUID(agent_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid agent ID")

    result = await db.execute(select(Agent).where(Agent.id == agent_uuid))
    agent = result.scalar_one_or_none()
    if not agent:
        raise HTTPException(status_code=404, detail="Agent not found")

    old_paths = (agent.desired_config or {}).get("paths")
    new_paths = [p.model_dump() for p in body.paths]
    agent.desired_config = {"paths": new_paths}
    agent.desired_config_version = (agent.desired_config_version or 0) + 1
    await db.commit()

    # Security-relevant: this changes what a monitoring agent actually
    # watches, so it needs a trail like any other admin action here.
    await AuditService.log(
        db, current_user.id, current_user.username, "AGENT_CONFIG_PUSHED",
        resource_type="agent", resource_id=agent.id,
        details={
            "hostname": agent.hostname,
            "old_paths": old_paths,
            "new_paths": new_paths,
            "desired_config_version": agent.desired_config_version,
        },
        ip_address=_client_ip(http_request),
    )
    await db.commit()

    return {
        "message": "Config pushed — agent will pick it up on next heartbeat",
        "desired_config_version": agent.desired_config_version,
    }


@router.get("/{agent_id}/config")
async def get_agent_config(
    agent_id: str,
    db: AsyncSession = Depends(get_db)
):
    """
    Current desired config for an agent — used by both the frontend editor
    and the agent's own pull. No get_current_user dependency: the agent
    authenticates via X-API-Key (like /register and /heartbeat), not a JWT
    bearer token, so it can't satisfy that dependency.
    """
    try:
        agent_uuid = uuid.UUID(agent_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid agent ID")

    result = await db.execute(select(Agent).where(Agent.id == agent_uuid))
    agent = result.scalar_one_or_none()
    if not agent:
        raise HTTPException(status_code=404, detail="Agent not found")

    return {
        "desired_config": agent.desired_config,
        "desired_config_version": agent.desired_config_version,
        "applied_config_version": agent.applied_config_version,
        # What the agent says it's actually running right now — display-only,
        # doesn't participate in the push/apply/ack protocol. Lets the editor
        # pre-fill with reality instead of a blank form when nothing's ever
        # been pushed to this agent via desired_config yet.
        "reported_config": agent.reported_config,
    }


@router.post("/{agent_id}/config/ack")
async def ack_agent_config(
    agent_id: str,
    request: AgentConfigAckRequest,
    db: AsyncSession = Depends(get_db)
):
    """Agent confirms it has applied a given config version."""
    try:
        agent_uuid = uuid.UUID(agent_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid agent ID")

    result = await db.execute(select(Agent).where(Agent.id == agent_uuid))
    agent = result.scalar_one_or_none()
    if not agent:
        raise HTTPException(status_code=404, detail="Agent not found")

    agent.applied_config_version = request.version
    await db.commit()

    return {"message": "Config version acknowledged", "applied_config_version": agent.applied_config_version}


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
