from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from pydantic import BaseModel, validator, Field, EmailStr, EmailStr
import re
from typing import List, Dict, Tuple, Set, Optional, List, Optional
import uuid
from datetime import datetime

from app.core.database import get_db
from app.core.security import create_access_token, verify_password, get_password_hash, validate_password_policy, get_current_user
from app.core.security_logger import log_password_change, log_role_change
from app.models.models import User

router = APIRouter()

class UserCreate(BaseModel):
    username: str = Field(..., min_length=3, max_length=50)
    email: EmailStr = Field(..., max_length=255)
    password: str = Field(..., min_length=8, max_length=128)
    full_name: Optional[str] = Field(None, max_length=255)
    role: str = Field("viewer", max_length=50)
    
    @validator('username')
    def validate_username(cls, v):
        """Username: alphanumeric, underscore, hyphen, dot only"""
        import re
        v = v.strip().lower()
        if not re.match(r'^[a-z0-9_\-\.]+$', v):
            raise ValueError('Username can only contain letters, numbers, underscore, hyphen, dot')
        if v in ['admin', 'root', 'system', 'null', 'undefined', 'test', 'guest']:
            raise ValueError('Reserved username not allowed')
        return v
    
    @validator('full_name')
    def validate_full_name(cls, v):
        """Sanitize full name"""
        if not v:
            return v
        from app.core.security import sanitize_string

# ── GAP #12: Session Revocation Helper ───────────────────────────
from sqlalchemy import text as _text
from typing import List, Dict, Tuple, Set, Optional, Optional as _Optional
import logging as _logging
_session_log = _logging.getLogger(__name__)

async def revoke_user_sessions(
    db,
    user_id,
    reason: str,
    exclude_jti: _Optional[str] = None
) -> int:
    """
    GAP #12: Revoke all active sessions for a user.
    Called on: role change, password change, account disable.

    Args:
        db         : AsyncSession
        user_id    : UUID of the user whose sessions to revoke
        reason     : one of role_change | password_change | account_disabled
        exclude_jti: JTI of current session to keep (for password change)

    Returns:
        Number of sessions revoked
    """
    try:
        if exclude_jti:
            result = await db.execute(_text("""
                UPDATE fim.sessions
                SET is_revoked   = true,
                    revoked_at   = NOW(),
                    revoke_reason = :reason
                WHERE user_id    = :user_id
                  AND is_revoked = false
                  AND expires_at > NOW()
                  AND jti       != :exclude_jti
            """), {"user_id": str(user_id),
                   "reason": reason,
                   "exclude_jti": exclude_jti})
        else:
            result = await db.execute(_text("""
                UPDATE fim.sessions
                SET is_revoked   = true,
                    revoked_at   = NOW(),
                    revoke_reason = :reason
                WHERE user_id    = :user_id
                  AND is_revoked = false
                  AND expires_at > NOW()
            """), {"user_id": str(user_id), "reason": reason})

        count = result.rowcount
        _session_log.info(
            "GAP#12: Revoked %d session(s) for user %s (reason: %s)",
            count, user_id, reason
        )
        return count
    except Exception as e:
        _session_log.error("GAP#12: Failed to revoke sessions: %s", e)
        return 0
# ── End GAP #12 Helper ────────────────────────────────────────────
        return sanitize_string(v, max_length=255, field_name="Full name")
    
    @validator('role')
    def validate_role(cls, v):
        """Validate role"""
        valid_roles = ['admin', 'analyst', 'trainee', 'auditor', 'viewer']
        if v.lower() not in valid_roles:
            raise ValueError(f'Invalid role. Must be one of: {", ".join(valid_roles)}')
        return v.lower()

class UserUpdate(BaseModel):
    full_name: Optional[str] = None
    role: Optional[str] = None
    password: Optional[str] = None
    is_active: Optional[bool] = None

class UserResponse(BaseModel):
    id: uuid.UUID
    username: str
    email: str
    full_name: Optional[str]
    role: str
    is_active: bool
    created_at: datetime

    class Config:
        from_attributes = True

@router.get("", response_model=List[UserResponse])
async def list_users(
    skip: int = 0, 
    limit: int = 100, 
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    if current_user.role != 'admin':
        raise HTTPException(status_code=403, detail="Not authorized")
    
    result = await db.execute(select(User).where(User.is_active == True).offset(skip).limit(limit))
    return result.scalars().all()

@router.post("", response_model=UserResponse)
async def create_user(
    user: UserCreate, 
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    if current_user.role != 'admin':
        raise HTTPException(status_code=403, detail="Not authorized")
    
    valid_roles = ['admin', 'analyst', 'trainee', 'auditor', 'viewer']
    if user.role.lower() not in valid_roles:
        raise HTTPException(status_code=400, detail=f"Invalid role. Must be one of: {valid_roles}")

    result = await db.execute(select(User).where(User.username == user.username))
    if result.scalar_one_or_none():
        raise HTTPException(status_code=400, detail="Username already registered")
    
    # Validate password policy (skip for SSO users)
    if user.password != "sso-managed":
        is_valid, error_msg = validate_password_policy(user.password)
        if not is_valid:
            raise HTTPException(
                status_code=400,
                detail=f"Password policy violation: {error_msg}"
            )
    
    hashed_pw = get_password_hash(user.password)
    new_user = User(
        id=uuid.uuid4(),
        username=user.username,
        email=user.email,
        password_hash=hashed_pw,
        full_name=user.full_name,
        role=user.role.lower(),
        is_active=True
    )
    
    db.add(new_user)
    await db.commit()
    await db.refresh(new_user)
    return new_user

@router.patch("/{user_id}", response_model=UserResponse)
async def update_user(
    user_id: uuid.UUID,
    updates: UserUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    if current_user.role != 'admin':
        raise HTTPException(status_code=403, detail="Not authorized")
    
    user = await db.get(User, user_id)
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    
    if updates.role:
        valid_roles = ['admin', 'analyst', 'trainee', 'auditor', 'viewer']
        if updates.role.lower() not in valid_roles:
            raise HTTPException(status_code=400, detail=f"Invalid role")
        user.role = updates.role.lower()

    # GAP #14: log role change
    log_role_change(
        target_user_id=str(user_id),
        new_role=str(new_role),
        changed_by=str(current_user.id),
        ip=request.client.host if request.client else 'unknown'
    )
        
    if updates.password:
        user.password_hash = get_password_hash(updates.password)

    # GAP #14: log password change
    log_password_change(
        user_id=str(user_id),
        changed_by=str(current_user.id),
        ip=request.client.host if request.client else 'unknown'
    )
        
    if updates.is_active is not None:
        user.is_active = updates.is_active
        
    user.updated_at = datetime.now()
    await db.commit()
    await db.refresh(user)
    return user

@router.delete("/{user_id}")
async def delete_user(
    user_id: uuid.UUID, 
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    if current_user.role != 'admin':
        raise HTTPException(status_code=403, detail="Not authorized")
    
    user = await db.get(User, user_id)
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
        
    await db.delete(user)
    await db.commit()
    return {"message": "User deleted"}
