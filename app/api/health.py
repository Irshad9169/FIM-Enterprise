"""
Health Check Endpoints
"""
from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import text
from app.core.database import get_db
import logging

router = APIRouter()
logger = logging.getLogger(__name__)

@router.get("")
@router.get("/")
async def health_check():
    """Basic health check"""
    return {
        "status": "healthy",
        "service": "FIM Server"
    }

@router.get("/detailed")
async def detailed_health_check(db: AsyncSession = Depends(get_db)):
    """Detailed health check with database connectivity"""
    try:
        # Test database connection
        result = await db.execute(text("SELECT 1"))
        result.scalar()
        
        return {
            "status": "healthy",
            "service": "FIM Server",
            "database": "connected"
        }
    except Exception as e:
        logger.error(f"Health check failed: {e}")
        return {
            "status": "unhealthy",
            "service": "FIM Server",
            "database": "disconnected",
            "error": str(e)
        }
