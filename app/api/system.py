import shutil

from fastapi import APIRouter, Depends
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.security import get_current_user
from app.models.models import User

router = APIRouter()

# Thresholds chosen from this project's own incident: fim-disk-cleanup.sh
# (OS-level cleanup) already treats 85%/92% as warning/critical for backups,
# journal, and log trimming -- reusing the same numbers here keeps one
# mental model for "disk is getting tight" instead of two disagreeing ones.
DISK_WARNING_PCT = 85
DISK_CRITICAL_PCT = 92


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
    autovacuum fix on fim.scans.
    """
    total, used, free = shutil.disk_usage("/")
    used_pct = round(used / total * 100, 1)

    if used_pct >= DISK_CRITICAL_PCT:
        status = "critical"
    elif used_pct >= DISK_WARNING_PCT:
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
        },
        "database": {
            "total_bytes": db_size_bytes,
            "top_tables": top_tables,
        },
    }
