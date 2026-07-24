"""
Test version of agents_enhanced
"""
from fastapi import APIRouter, Depends
from app.core.database import get_db
from app.core.rbac import require_role
from app.models import User
from sqlalchemy.ext.asyncio import AsyncSession

router = APIRouter()

@router.get("/test")
async def test_endpoint(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_role(['admin', 'analyst', 'trainee', 'auditor']))
):
    """Simple test endpoint"""
    return {
        "status": "ok",
        "message": "agents_enhanced is working",
        "user": current_user.username
    }
