"""
Anomaly Detection API — GAP #19
Exposes anomaly scores and triggers manual detection runs.
"""

import logging
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.security import get_current_user
from app.services.anomaly_detector import (
    run_anomaly_detection,
    get_latest_anomaly_scores,
)

router = APIRouter()
logger = logging.getLogger(__name__)


@router.get("")
async def list_anomaly_scores(
    db: AsyncSession = Depends(get_db),
    current_user=Depends(get_current_user),
):
    """
    GAP #19: Return latest anomaly score per agent.
    Used by dashboard widget.
    """
    try:
        scores = await get_latest_anomaly_scores(db)
        total_anomalous = sum(1 for s in scores if s["score"] > 30)
        return {
            "scores": scores,
            "total_agents": len(scores),
            "anomalous_agents": total_anomalous,
        }
    except Exception as e:
        logger.error("Anomaly list error: %s", e)
        return {"scores": [], "total_agents": 0, "anomalous_agents": 0}


@router.post("/run")
async def trigger_anomaly_detection(
    db: AsyncSession = Depends(get_db),
    current_user=Depends(get_current_user),
):
    """
    GAP #19: Manually trigger anomaly detection run.
    Admin/analyst only.
    """
    if current_user.role not in ("admin", "analyst"):
        raise HTTPException(403, "Insufficient permissions")

    anomalies = await run_anomaly_detection(db)
    return {
        "message": "Anomaly detection completed",
        "anomalies_found": len(anomalies),
        "anomalies": anomalies[:10],  # return top 10
    }
