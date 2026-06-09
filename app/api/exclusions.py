from fastapi import APIRouter, Depends, HTTPException, UploadFile, File
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, text
from typing import List, Dict, Tuple, Set, Optional, Optional, List
from datetime import datetime
import uuid

from app.core.database import get_db
from app.core.security import get_current_user
from app.models.models import User
from pydantic import BaseModel, UUID4

router = APIRouter()


# ============================================================================
# Pydantic Schemas
# ============================================================================

class ExclusionRuleCreate(BaseModel):
    rule_name: str
    rule_type: str  # 'path', 'glob', 'regex'
    match_value: str
    reason: Optional[str] = None
    scope: str = 'global'  # 'global' or 'agent'
    agent_id: Optional[UUID4] = None


class ExclusionRuleUpdate(BaseModel):
    rule_name: Optional[str] = None
    reason: Optional[str] = None
    is_active: Optional[bool] = None


class ExclusionRuleResponse(BaseModel):
    id: UUID4
    rule_name: str
    rule_type: str
    match_value: str
    reason: Optional[str]
    scope: str
    agent_id: Optional[UUID4]
    agent_hostname: Optional[str]
    is_active: bool
    match_count: int
    created_at: datetime

    class Config:
        from_attributes = True


class AgentExclusionsResponse(BaseModel):
    agent_id: UUID4
    hostname: str
    global_rules: List[ExclusionRuleResponse]
    agent_specific_rules: List[ExclusionRuleResponse]
    total_effective_rules: int


# ============================================================================
# Global Exclusions (Apply to ALL agents)
# ============================================================================

@router.get("/global", response_model=List[ExclusionRuleResponse])
async def list_global_exclusions(
    is_active: Optional[bool] = None,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """List global exclusion rules that apply to all agents"""
    
    query = """
        SELECT 
            id, rule_name, rule_type, match_value, reason, scope,
            agent_id, is_active, match_count, created_at
        FROM fim.whitelist_rules
        WHERE scope = 'global'
    """
    
    params = {}
    
    if is_active is not None:
        query += " AND is_active = :is_active"
        params['is_active'] = is_active
    
    query += " ORDER BY rule_type, match_value"
    
    result = await db.execute(text(query), params)
    rows = result.fetchall()
    
    return [
        ExclusionRuleResponse(
            id=row.id,
            rule_name=row.rule_name,
            rule_type=row.rule_type,
            match_value=row.match_value,
            reason=row.reason,
            scope=row.scope,
            agent_id=None,
            agent_hostname=None,
            is_active=row.is_active,
            match_count=row.match_count or 0,
            created_at=row.created_at
        )
        for row in rows
    ]


@router.post("/global", response_model=ExclusionRuleResponse)
async def create_global_exclusion(
    rule: ExclusionRuleCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Create a new global exclusion rule (applies to all agents)"""
    
    # Force scope to global
    rule.scope = 'global'
    rule.agent_id = None
    
    # Validate rule_type
    if rule.rule_type not in ['path', 'glob', 'regex']:
        raise HTTPException(status_code=400, detail="rule_type must be 'path', 'glob', or 'regex'")
    
    # Check for duplicates
    result = await db.execute(
        text("SELECT id FROM fim.whitelist_rules WHERE match_value = :match_value AND scope = 'global'"),
        {'match_value': rule.match_value}
    )
    if result.scalar_one_or_none():
        raise HTTPException(status_code=400, detail="This global exclusion already exists")
    
    # Insert new rule
    rule_id = uuid.uuid4()
    result = await db.execute(
        text("""
            INSERT INTO fim.whitelist_rules (
                id, rule_name, rule_type, match_value, reason, scope,
                is_active, is_temporary, created_by, created_at, match_count
            ) VALUES (
                :id, :rule_name, :rule_type, :match_value, :reason, 'global',
                true, false, :created_by, NOW(), 0
            )
            RETURNING id, rule_name, rule_type, match_value, reason, scope,
                      is_active, match_count, created_at
        """),
        {
            'id': str(rule_id),
            'rule_name': rule.rule_name,
            'rule_type': rule.rule_type,
            'match_value': rule.match_value,
            'reason': rule.reason,
            'created_by': str(current_user.id)
        }
    )
    await db.commit()
    
    row = result.fetchone()
    
    return ExclusionRuleResponse(
        id=row.id,
        rule_name=row.rule_name,
        rule_type=row.rule_type,
        match_value=row.match_value,
        reason=row.reason,
        scope=row.scope,
        agent_id=None,
        agent_hostname=None,
        is_active=row.is_active,
        match_count=row.match_count or 0,
        created_at=row.created_at
    )


# ============================================================================
# Agent-Specific Exclusions (Additional rules for specific agents)
# ============================================================================

@router.get("/agents/{agent_id}", response_model=AgentExclusionsResponse)
async def get_agent_exclusions(
    agent_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Get all effective exclusions for a specific agent (global + agent-specific)"""
    
    try:
        agent_uuid = uuid.UUID(agent_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid agent ID")
    
    # Get agent info
    agent_result = await db.execute(
        text("SELECT id, hostname FROM fim.agents WHERE id = :id"),
        {'id': str(agent_uuid)}
    )
    agent = agent_result.fetchone()
    
    if not agent:
        raise HTTPException(status_code=404, detail="Agent not found")
    
    # Get global rules
    global_result = await db.execute(
        text("""
            SELECT id, rule_name, rule_type, match_value, reason, scope,
                   is_active, match_count, created_at
            FROM fim.whitelist_rules
            WHERE scope = 'global' AND is_active = true AND status = 'approved'
            ORDER BY rule_type, match_value
        """)
    )
    
    global_rules = [
        ExclusionRuleResponse(
            id=row.id,
            rule_name=row.rule_name,
            rule_type=row.rule_type,
            match_value=row.match_value,
            reason=row.reason,
            scope=row.scope,
            agent_id=None,
            agent_hostname=None,
            is_active=row.is_active,
            match_count=row.match_count or 0,
            created_at=row.created_at
        )
        for row in global_result.fetchall()
    ]
    
    # Get agent-specific rules
    agent_result = await db.execute(
        text("""
            SELECT id, rule_name, rule_type, match_value, reason, scope,
                   is_active, match_count, created_at
            FROM fim.whitelist_rules
            WHERE scope = 'agent' AND agent_id = :agent_id AND is_active = true
            ORDER BY rule_type, match_value
        """),
        {'agent_id': str(agent_uuid)}
    )
    
    agent_rules = [
        ExclusionRuleResponse(
            id=row.id,
            rule_name=row.rule_name,
            rule_type=row.rule_type,
            match_value=row.match_value,
            reason=row.reason,
            scope=row.scope,
            agent_id=agent_uuid,
            agent_hostname=agent.hostname,
            is_active=row.is_active,
            match_count=row.match_count or 0,
            created_at=row.created_at
        )
        for row in agent_result.fetchall()
    ]
    
    return AgentExclusionsResponse(
        agent_id=agent.id,
        hostname=agent.hostname,
        global_rules=global_rules,
        agent_specific_rules=agent_rules,
        total_effective_rules=len(global_rules) + len(agent_rules)
    )


@router.post("/agents/{agent_id}", response_model=ExclusionRuleResponse)
async def add_agent_exclusion(
    agent_id: str,
    rule: ExclusionRuleCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Add an agent-specific exclusion (in addition to global rules)"""
    
    try:
        agent_uuid = uuid.UUID(agent_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid agent ID")
    
    # Verify agent exists
    agent_result = await db.execute(
        text("SELECT id, hostname FROM fim.agents WHERE id = :id"),
        {'id': str(agent_uuid)}
    )
    agent = agent_result.fetchone()
    
    if not agent:
        raise HTTPException(status_code=404, detail="Agent not found")
    
    # Force scope to agent
    rule.scope = 'agent'
    rule.agent_id = agent_uuid
    
    # Check for duplicates
    result = await db.execute(
        text("""
            SELECT id FROM fim.whitelist_rules 
            WHERE match_value = :match_value 
              AND scope = 'agent' 
              AND agent_id = :agent_id
        """),
        {'match_value': rule.match_value, 'agent_id': str(agent_uuid)}
    )
    if result.scalar_one_or_none():
        raise HTTPException(status_code=400, detail="This agent-specific exclusion already exists")
    
    # Insert new rule
    rule_id = uuid.uuid4()
    result = await db.execute(
        text("""
            INSERT INTO fim.whitelist_rules (
                id, rule_name, rule_type, match_value, reason, scope, agent_id,
                is_active, is_temporary, created_by, created_at, match_count
            ) VALUES (
                :id, :rule_name, :rule_type, :match_value, :reason, 'agent', :agent_id,
                true, false, :created_by, NOW(), 0
            )
            RETURNING id, rule_name, rule_type, match_value, reason, scope,
                      is_active, match_count, created_at
        """),
        {
            'id': str(rule_id),
            'rule_name': rule.rule_name,
            'rule_type': rule.rule_type,
            'match_value': rule.match_value,
            'reason': rule.reason,
            'agent_id': str(agent_uuid),
            'created_by': str(current_user.id)
        }
    )
    await db.commit()
    
    row = result.fetchone()
    
    return ExclusionRuleResponse(
        id=row.id,
        rule_name=row.rule_name,
        rule_type=row.rule_type,
        match_value=row.match_value,
        reason=row.reason,
        scope=row.scope,
        agent_id=agent_uuid,
        agent_hostname=agent.hostname,
        is_active=row.is_active,
        match_count=row.match_count or 0,
        created_at=row.created_at
    )


# ============================================================================
# Common Operations (Works for both global and agent-specific)
# ============================================================================

@router.patch("/{rule_id}", response_model=ExclusionRuleResponse)
async def update_exclusion(
    rule_id: str,
    updates: ExclusionRuleUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Update an exclusion rule (edit name, reason, or enable/disable)"""
    
    try:
        rule_uuid = uuid.UUID(rule_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid rule ID")
    
    # Build dynamic update query
    update_parts = []
    params = {'id': str(rule_uuid)}
    
    if updates.rule_name is not None:
        update_parts.append("rule_name = :rule_name")
        params['rule_name'] = updates.rule_name
    
    if updates.reason is not None:
        update_parts.append("reason = :reason")
        params['reason'] = updates.reason
    
    if updates.is_active is not None:
        update_parts.append("is_active = :is_active")
        params['is_active'] = updates.is_active
    
    if not update_parts:
        raise HTTPException(status_code=400, detail="No updates provided")
    
    query = f"""
        UPDATE fim.whitelist_rules
        SET {', '.join(update_parts)}
        WHERE id = :id
        RETURNING id, rule_name, rule_type, match_value, reason, scope, agent_id,
                  is_active, match_count, created_at
    """
    
    result = await db.execute(text(query), params)
    row = result.fetchone()
    
    if not row:
        raise HTTPException(status_code=404, detail="Rule not found")
    
    await db.commit()
    
    # Get agent hostname if agent-specific
    agent_hostname = None
    if row.agent_id:
        agent_result = await db.execute(
            text("SELECT hostname FROM fim.agents WHERE id = :id"),
            {'id': str(row.agent_id)}
        )
        agent_row = agent_result.fetchone()
        if agent_row:
            agent_hostname = agent_row.hostname
    
    return ExclusionRuleResponse(
        id=row.id,
        rule_name=row.rule_name,
        rule_type=row.rule_type,
        match_value=row.match_value,
        reason=row.reason,
        scope=row.scope,
        agent_id=row.agent_id,
        agent_hostname=agent_hostname,
        is_active=row.is_active,
        match_count=row.match_count or 0,
        created_at=row.created_at
    )


@router.delete("/{rule_id}")
async def delete_exclusion(
    rule_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Delete an exclusion rule"""
    
    try:
        rule_uuid = uuid.UUID(rule_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid rule ID")
    
    result = await db.execute(
        text("DELETE FROM fim.whitelist_rules WHERE id = :id RETURNING id, scope"),
        {'id': str(rule_uuid)}
    )
    
    row = result.fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="Rule not found")
    
    await db.commit()
    
    return {
        "message": f"{row.scope.capitalize()} exclusion rule deleted successfully"
    }


@router.post("/{rule_id}/toggle")
async def toggle_exclusion(
    rule_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Enable/disable an exclusion rule"""
    
    try:
        rule_uuid = uuid.UUID(rule_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid rule ID")
    
    result = await db.execute(
        text("""
            UPDATE fim.whitelist_rules 
            SET is_active = NOT is_active 
            WHERE id = :id 
            RETURNING id, is_active
        """),
        {'id': str(rule_uuid)}
    )
    
    row = result.fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="Rule not found")
    
    await db.commit()
    
    return {
        "message": f"Rule {'enabled' if row.is_active else 'disabled'}",
        "is_active": row.is_active
    }


# ============================================================================
# Bulk Import/Export
# ============================================================================

@router.post("/import")
async def import_exclusions(
    file: UploadFile = File(...),
    scope: str = 'global',
    agent_id: Optional[str] = None,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Import exclusions from text file"""
    
    if scope not in ['global', 'agent']:
        raise HTTPException(status_code=400, detail="scope must be 'global' or 'agent'")
    
    if scope == 'agent' and not agent_id:
        raise HTTPException(status_code=400, detail="agent_id required for agent-specific import")
    
    content = await file.read()
    lines = content.decode('utf-8').splitlines()
    
    imported = 0
    skipped = 0
    errors = []
    
    for line_num, line in enumerate(lines, 1):
        line = line.strip()
        
        if not line or line.startswith('#'):
            skipped += 1
            continue
        
        try:
            # Determine rule type
            if line.startswith('regex:'):
                rule_type = 'regex'
                match_value = line[6:].strip()
                rule_name = f"Regex: {match_value[:50]}"
            elif '*' in line:
                rule_type = 'glob'
                match_value = line
                rule_name = f"Pattern: {match_value}"
            else:
                rule_type = 'path'
                match_value = line
                rule_name = f"Path: {match_value}"
            
            rule_id = uuid.uuid4()
            await db.execute(
                text("""
                    INSERT INTO fim.whitelist_rules (
                        id, rule_name, rule_type, match_value, reason, scope, agent_id,
                        is_active, is_temporary, created_by, created_at, match_count
                    ) VALUES (
                        :id, :rule_name, :rule_type, :match_value, :reason, :scope, :agent_id,
                        true, false, :created_by, NOW(), 0
                    )
                    ON CONFLICT DO NOTHING
                """),
                {
                    'id': str(rule_id),
                    'rule_name': rule_name,
                    'rule_type': rule_type,
                    'match_value': match_value,
                    'reason': f"Imported from {file.filename} (line {line_num})",
                    'scope': scope,
                    'agent_id': agent_id,
                    'created_by': str(current_user.id)
                }
            )
            imported += 1
            
        except Exception as e:
            errors.append(f"Line {line_num}: {str(e)}")
            skipped += 1
    
    await db.commit()
    
    return {
        "imported": imported,
        "skipped": skipped,
        "errors": errors
    }


@router.get("/export")
async def export_exclusions(
    scope: Optional[str] = 'global',
    agent_id: Optional[str] = None,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Export exclusions to text file"""
    
    query = "SELECT rule_type, match_value, reason FROM fim.whitelist_rules WHERE is_active = true"
    params = {}
    
    if scope:
        query += " AND scope = :scope"
        params['scope'] = scope
    
    if agent_id:
        query += " AND agent_id = :agent_id"
        params['agent_id'] = agent_id
    
    query += " ORDER BY rule_type, match_value"
    
    result = await db.execute(text(query), params)
    rows = result.fetchall()
    
    lines = [
        "# FIM Exclusion Rules",
        f"# Exported: {datetime.now().isoformat()}",
        f"# Scope: {scope}",
        ""
    ]
    
    for row in rows:
        if row.reason:
            lines.append(f"# {row.reason}")
        
        if row.rule_type == 'regex':
            lines.append(f"regex:{row.match_value}")
        else:
            lines.append(row.match_value)
        
        lines.append("")
    
    from fastapi.responses import Response
    return Response(
        content="\n".join(lines),
        media_type="text/plain",
        headers={
            "Content-Disposition": f"attachment; filename=fim-exclusions-{scope}-{datetime.now().strftime('%Y%m%d')}.txt"
        }
    )


@router.get("/stats")
async def get_stats(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Get exclusion statistics"""
    
    result = await db.execute(text("""
        SELECT 
            scope,
            COUNT(*) as total,
            SUM(CASE WHEN is_active THEN 1 ELSE 0 END) as active,
            SUM(match_count) as total_matches
        FROM fim.whitelist_rules
        GROUP BY scope
    """))
    
    stats = {}
    for row in result.fetchall():
        stats[row.scope] = {
            'total': row.total,
            'active': row.active,
            'total_matches': row.total_matches or 0
        }
    
    return stats


# ── Exclusion Approval Hardening ─────────────────────────────────
from datetime import datetime, timezone as _tz

@router.get("/pending")
async def list_pending_exclusions(
    db: AsyncSession = Depends(get_db),
    current_user = Depends(get_current_user)
):
    """Admin-only: List all pending whitelist rules awaiting approval."""
    if getattr(current_user, 'role', None) != 'admin':
        raise HTTPException(403, "Admin role required")
    result = await db.execute(text("""
        SELECT e.id, e.rule_name, e.rule_type, e.match_value, e.reason,
               e.scope, e.created_at, u.username as created_by_username
        FROM fim.whitelist_rules e
        LEFT JOIN fim.users u ON e.created_by = u.id
        WHERE e.status = 'pending'
        ORDER BY e.created_at ASC
    """))
    rows = result.fetchall()
    return {"pending": [dict(r._mapping) for r in rows], "count": len(rows)}


@router.post("/{exclusion_id}/approve")
async def approve_exclusion(
    exclusion_id: str,
    db: AsyncSession = Depends(get_db),
    current_user = Depends(get_current_user)
):
    """Admin-only: Approve a pending whitelist rule."""
    if getattr(current_user, 'role', None) != 'admin':
        raise HTTPException(403, "Admin role required")

    result = await db.execute(text(
        "SELECT id, match_value, status FROM fim.whitelist_rules WHERE id = :id"
    ), {"id": exclusion_id})
    rule = result.fetchone()
    if not rule:
        raise HTTPException(404, "Rule not found")
    if rule.status != 'pending':
        raise HTTPException(400, f"Can only approve pending rules (current: {rule.status})")

    await db.execute(text("""
        UPDATE fim.whitelist_rules
        SET status = 'approved', approved_by = :admin_id, approved_at = :now
        WHERE id = :id
    """), {"admin_id": str(current_user.id), "now": datetime.now(_tz.utc), "id": exclusion_id})
    await db.commit()

    try:
        from app.core.security_logger import security_log
        security_log("exclusion_approved", level="INFO",
                     exclusion_id=exclusion_id,
                     match_value=rule.match_value,
                     approved_by=current_user.username)
    except Exception:
        pass

    return {"message": "Rule approved", "id": exclusion_id, "match_value": rule.match_value}


@router.post("/{exclusion_id}/reject")
async def reject_exclusion(
    exclusion_id: str,
    reason: str = "",
    db: AsyncSession = Depends(get_db),
    current_user = Depends(get_current_user)
):
    """Admin-only: Reject a pending whitelist rule."""
    if getattr(current_user, 'role', None) != 'admin':
        raise HTTPException(403, "Admin role required")

    result = await db.execute(text(
        "SELECT id, match_value, status FROM fim.whitelist_rules WHERE id = :id"
    ), {"id": exclusion_id})
    rule = result.fetchone()
    if not rule:
        raise HTTPException(404, "Rule not found")
    if rule.status != 'pending':
        raise HTTPException(400, f"Can only reject pending rules (current: {rule.status})")

    await db.execute(text("""
        UPDATE fim.whitelist_rules
        SET status = 'rejected', rejection_reason = :reason
        WHERE id = :id
    """), {"reason": reason or "No reason provided", "id": exclusion_id})
    await db.commit()

    try:
        from app.core.security_logger import security_log
        security_log("exclusion_rejected", level="WARNING",
                     exclusion_id=exclusion_id,
                     match_value=rule.match_value,
                     rejected_by=current_user.username,
                     reason=reason)
    except Exception:
        pass

    return {"message": "Rule rejected", "id": exclusion_id, "reason": reason or "No reason provided"}

# ── End Exclusion Approval Hardening ─────────────────────────────

