"""Session Management API"""
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from app.core.database import get_db
from app.core.security import get_current_user
from app.core.time_utils import as_utc
from app.models.models import User
from app.services.session_service import SessionService

router = APIRouter()


@router.get("")
async def list_active_sessions(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """List all active sessions (admin only)."""
    if current_user.role not in ("admin", "superadmin"):
        raise HTTPException(403, "Admin access required")
    sessions = await SessionService.get_all_active_sessions(db)
    for s in sessions:
        for k in s:
            if hasattr(s[k], 'isoformat'):
                s[k] = as_utc(s[k]).isoformat()
        s['user_id'] = str(s['user_id'])
        s['id'] = str(s['id'])
    return {"sessions": sessions}


@router.get("/me")
async def my_sessions(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """List current user's sessions."""
    sessions = await SessionService.get_user_sessions(db, str(current_user.id))
    for s in sessions:
        for k in s:
            if hasattr(s[k], 'isoformat'):
                s[k] = as_utc(s[k]).isoformat()
        s['id'] = str(s['id'])
    return {"sessions": sessions}


@router.post("/{session_id}/revoke")
async def revoke_session(
    session_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Revoke a specific session."""
    if current_user.role not in ("admin", "superadmin"):
        raise HTTPException(403, "Admin access required")
    await SessionService.revoke_session(db, session_id, str(current_user.id))
    await db.commit()
    return {"message": "Session revoked"}


@router.post("/user/{user_id}/revoke-all")
async def revoke_all(
    user_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Revoke all sessions for a user (force logout)."""
    if current_user.role not in ("admin", "superadmin"):
        raise HTTPException(403, "Admin access required")
    await SessionService.revoke_all_user_sessions(db, user_id, str(current_user.id))
    await db.commit()
    return {"message": "All sessions revoked"}
