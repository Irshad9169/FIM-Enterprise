"""
Whitelist Management Endpoints
"""
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, text
from pydantic import BaseModel
from typing import Optional
from datetime import datetime, timedelta
import uuid

from app.core.database import get_db
from app.core.security import get_current_user
from app.models import User
from app.services.whitelist_checker import WhitelistChecker

router = APIRouter()

class WhitelistRuleCreate(BaseModel):
    rule_name: str
    rule_type: str  # 'path', 'pattern', 'hash', 'directory', 'extension'
    match_value: str
    reason: Optional[str] = None
    severity_override: Optional[str] = None  # 'low', 'medium', etc.
    is_temporary: bool = False
    expires_in_hours: Optional[int] = None

@router.post("/rules")
async def create_whitelist_rule(
    request: WhitelistRuleCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Create a new whitelist rule"""
    
    # Validate rule_type
    valid_types = ['path', 'pattern', 'hash', 'directory', 'extension']
    if request.rule_type not in valid_types:
        raise HTTPException(400, f"Invalid rule_type. Must be one of: {valid_types}")
    
    # Calculate expiry if temporary
    expires_at = None
    if request.is_temporary and request.expires_in_hours:
        expires_at = datetime.utcnow() + timedelta(hours=request.expires_in_hours)
    
    rule_id = uuid.uuid4()
    
    try:
        await db.execute(
            text("""
                INSERT INTO fim.whitelist_rules
                (id, rule_name, rule_type, match_value, reason, severity_override,
                 is_temporary, expires_at, created_by)
                VALUES (:id, :name, :type, :value, :reason, :severity,
                        :temp, :expires, :user)
            """),
            {
                'id': str(rule_id),
                'name': request.rule_name,
                'type': request.rule_type,
                'value': request.match_value,
                'reason': request.reason,
                'severity': request.severity_override,
                'temp': request.is_temporary,
                'expires': expires_at,
                'user': str(current_user.id)
            }
        )
        
        await db.commit()
        
        return {
            'success': True,
            'rule_id': str(rule_id),
            'message': 'Whitelist rule created',
            'expires_at': expires_at.isoformat() if expires_at else None
        }
    
    except Exception as e:
        if 'unique' in str(e).lower():
            raise HTTPException(400, "Rule name already exists")
        raise

@router.get("/rules")
async def list_whitelist_rules(
    active_only: bool = True,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """List all whitelist rules"""
    
    query = """
        SELECT id, rule_name, rule_type, match_value, reason, severity_override,
               is_active, is_temporary, expires_at, match_count, last_matched_at, created_at
        FROM fim.whitelist_rules
    """
    
    if active_only:
        query += " WHERE is_active = TRUE AND (is_temporary = FALSE OR expires_at > NOW())"
    
    query += " ORDER BY created_at DESC"
    
    result = await db.execute(text(query))
    rules = result.fetchall()
    
    return {
        'rules': [
            {
                'id': str(r[0]),
                'rule_name': r[1],
                'rule_type': r[2],
                'match_value': r[3],
                'reason': r[4],
                'severity_override': r[5],
                'is_active': r[6],
                'is_temporary': r[7],
                'expires_at': r[8].isoformat() if r[8] else None,
                'match_count': r[9],
                'last_matched_at': r[10].isoformat() if r[10] else None,
                'created_at': r[11].isoformat() if r[11] else None
            }
            for r in rules
        ],
        'total': len(rules)
    }

@router.delete("/rules/{rule_id}")
async def delete_whitelist_rule(
    rule_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Delete a whitelist rule"""
    try:
        rule_uuid = uuid.UUID(rule_id)
    except ValueError:
        raise HTTPException(400, "Invalid rule ID")
    
    result = await db.execute(
        text("DELETE FROM fim.whitelist_rules WHERE id = :id RETURNING id"),
        {'id': str(rule_uuid)}
    )
    
    if result.rowcount == 0:
        raise HTTPException(404, "Rule not found")
    
    await db.commit()
    
    return {'success': True, 'message': 'Rule deleted'}

@router.post("/rules/{rule_id}/toggle")
async def toggle_whitelist_rule(
    rule_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Enable/disable a whitelist rule"""
    try:
        rule_uuid = uuid.UUID(rule_id)
    except ValueError:
        raise HTTPException(400, "Invalid rule ID")
    
    result = await db.execute(
        text("""
            UPDATE fim.whitelist_rules
            SET is_active = NOT is_active
            WHERE id = :id
            RETURNING is_active
        """),
        {'id': str(rule_uuid)}
    )
    
    row = result.fetchone()
    if not row:
        raise HTTPException(404, "Rule not found")
    
    await db.commit()
    
    return {
        'success': True,
        'is_active': row[0],
        'message': f"Rule {'enabled' if row[0] else 'disabled'}"
    }

@router.get("/matches")
async def list_whitelist_matches(
    rule_id: Optional[str] = None,
    limit: int = 100,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """List recent whitelist matches"""
    
    query = """
        SELECT wm.id, wm.file_path, wm.matched_at, wm.suppressed_alert,
               wr.rule_name, wr.rule_type
        FROM fim.whitelist_matches wm
        JOIN fim.whitelist_rules wr ON wm.rule_id = wr.id
    """
    
    params = {'limit': limit}
    
    if rule_id:
        query += " WHERE wm.rule_id = :rule_id"
        params['rule_id'] = rule_id
    
    query += " ORDER BY wm.matched_at DESC LIMIT :limit"
    
    result = await db.execute(text(query), params)
    matches = result.fetchall()
    
    return {
        'matches': [
            {
                'id': str(m[0]),
                'file_path': m[1],
                'matched_at': m[2].isoformat() if m[2] else None,
                'suppressed_alert': m[3],
                'rule_name': m[4],
                'rule_type': m[5]
            }
            for m in matches
        ],
        'total': len(matches)
    }
