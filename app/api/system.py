import shutil
import uuid
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.security import get_current_user
from app.core.rbac import admin_only
from app.models.models import User, SystemSettings

router = APIRouter()

# Single settings row -- see migration 0012_system_settings. Simpler than a
# generic key/value table for the handful of tunables this needs so far.
SETTINGS_ROW_ID = uuid.UUID("00000000-0000-0000-0000-000000000001")


async def _get_settings(db: AsyncSession) -> SystemSettings:
    result = await db.execute(select(SystemSettings).where(SystemSettings.id == SETTINGS_ROW_ID))
    settings = result.scalar_one_or_none()
    if settings:
        return settings
    # Defensive fallback -- the migration seeds this row, but don't 500 the
    # whole health check if it's ever missing (e.g. a hand-edited DB).
    settings = SystemSettings(id=SETTINGS_ROW_ID, disk_warning_pct=85.0, disk_critical_pct=92.0)
    db.add(settings)
    await db.commit()
    return settings


@router.get("/disk-health")
async def get_disk_health(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    Disk usage plus the largest Postgres tables by total size (table +
    indexes + TOAST). Added after fim.scans silently grew to 27GB of mostly
    dead TOAST (cleanup_scan_data.sh nulled old scan_data but never
    VACUUMed, and autovacuum's row-count-based thresholds never noticed)
    and took the disk to 0 bytes free with nobody watching this number
    until Postgres itself crashed. See migration 0011 for the matching
    autovacuum fix on fim.scans, and 0012 for the configurable thresholds.
    """
    settings = await _get_settings(db)

    total, used, free = shutil.disk_usage("/")
    used_pct = round(used / total * 100, 1)

    if used_pct >= float(settings.disk_critical_pct):
        status = "critical"
    elif used_pct >= float(settings.disk_warning_pct):
        status = "warning"
    else:
        status = "ok"

    tables_result = await db.execute(text("""
        SELECT relname,
               pg_total_relation_size(relid) AS total_bytes,
               pg_relation_size(relid) AS table_bytes
        FROM pg_catalog.pg_statio_user_tables
        ORDER BY pg_total_relation_size(relid) DESC
        LIMIT 10
    """))
    top_tables = [
        {
            "name": row.relname,
            "total_bytes": row.total_bytes,
            "table_bytes": row.table_bytes,
        }
        for row in tables_result.fetchall()
    ]

    db_size_result = await db.execute(text("SELECT pg_database_size(current_database()) AS size"))
    db_size_bytes = db_size_result.scalar()

    return {
        "disk": {
            "total_bytes": total,
            "used_bytes": used,
            "free_bytes": free,
            "used_pct": used_pct,
            "status": status,
            "warning_pct": float(settings.disk_warning_pct),
            "critical_pct": float(settings.disk_critical_pct),
        },
        "database": {
            "total_bytes": db_size_bytes,
            "top_tables": top_tables,
        },
    }


@router.get("/settings")
async def get_system_settings(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    settings = await _get_settings(db)
    return {
        "disk_warning_pct": float(settings.disk_warning_pct),
        "disk_critical_pct": float(settings.disk_critical_pct),
        "updated_at": settings.updated_at.isoformat() if settings.updated_at else None,
    }


class UpdateSystemSettings(BaseModel):
    disk_warning_pct: float = Field(ge=1, le=99)
    disk_critical_pct: float = Field(ge=1, le=99)


@router.put("/settings")
async def update_system_settings(
    body: UpdateSystemSettings,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(admin_only),
):
    if body.disk_warning_pct >= body.disk_critical_pct:
        raise HTTPException(400, "Warning threshold must be lower than critical threshold")

    settings = await _get_settings(db)
    settings.disk_warning_pct = body.disk_warning_pct
    settings.disk_critical_pct = body.disk_critical_pct
    settings.updated_at = datetime.utcnow()
    settings.updated_by = current_user.id
    await db.commit()

    return {
        "disk_warning_pct": float(settings.disk_warning_pct),
        "disk_critical_pct": float(settings.disk_critical_pct),
    }
