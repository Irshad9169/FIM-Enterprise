from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import text
from app.core.database import get_db
from app.core.security import get_current_user
from app.models.models import User

router = APIRouter()

@router.get("/stats")
async def get_dashboard_stats(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Get overall dashboard statistics"""
    
    # Alert counts
    alert_stats = await db.execute(text("""
        SELECT 
            COUNT(*) as total,
            COUNT(*) FILTER (WHERE status = 'open') as open,
            COUNT(*) FILTER (WHERE severity = 'critical') as critical,
            COUNT(*) FILTER (WHERE severity = 'high') as high
        FROM fim.alerts
    """))
    alerts = alert_stats.fetchone()
    
    # Agent counts
    agent_stats = await db.execute(text("""
        SELECT 
            COUNT(*) as total,
            COUNT(*) FILTER (WHERE status = 'online') as online,
            COUNT(*) FILTER (WHERE is_healthy = true) as healthy
        FROM fim.agents
    """))
    agents = agent_stats.fetchone()
    
    return {
        "alerts": {
            "total": alerts.total,
            "open": alerts.open,
            "critical": alerts.critical,
            "high": alerts.high
        },
        "agents": {
            "total": agents.total,
            "online": agents.online,
            "healthy": agents.healthy
        }
    }

@router.get("/alerts/stats")
async def get_alert_stats(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Get detailed alert statistics"""
    
    # By Severity
    severity = await db.execute(text("""
        SELECT severity, COUNT(*) as count 
        FROM fim.alerts WHERE status = 'open'
        GROUP BY severity
    """))
    
    # By Status
    status = await db.execute(text("""
        SELECT status, COUNT(*) as count 
        FROM fim.alerts 
        GROUP BY status
    """))
    
    severity_dict = {row.severity: row.count for row in severity.fetchall()}
    status_dict = {row.status: row.count for row in status.fetchall()}
    
    # Calculate totals
    total = sum(severity_dict.values())
    
    return {
        "total_alerts": total,
        "by_severity": {
            "critical": severity_dict.get('critical', 0),
            "high": severity_dict.get('high', 0),
            "medium": severity_dict.get('medium', 0),
            "low": severity_dict.get('low', 0)
        },
        "by_status": {
            "open": status_dict.get('open', 0),
            "acknowledged": status_dict.get('acknowledged', 0),
            "resolved": status_dict.get('resolved', 0)
        }
    }

@router.get("/agents/health")
async def get_agent_health(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Get agent health summary"""
    
    stats = await db.execute(text("""
        SELECT 
            COUNT(*) as total,
            COUNT(*) FILTER (WHERE is_healthy = true) as healthy,
            COUNT(*) FILTER (WHERE is_healthy = false AND status = 'online') as unhealthy,
            COUNT(*) FILTER (WHERE status = 'offline') as offline,
            COUNT(*) FILTER (WHERE status = 'online') as online_agents
        FROM fim.agents
    """))
    row = stats.fetchone()
    
    return {
        "total_agents": row.total,
        "healthy_agents": row.healthy,
        "unhealthy_agents": row.unhealthy,
        "stale_agents": row.offline,  # Using offline as stale for now
        "online_agents": row.online_agents
    }

@router.get("/alerts/recent")
async def get_recent_alerts(
    limit: int = 10,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Get recent alerts for dashboard feed"""
    
    result = await db.execute(text(f"""
        SELECT 
            a.id, a.file_path, a.alert_type, a.severity, a.status, a.created_at,
            ag.hostname as agent_hostname
        FROM fim.alerts a
        LEFT JOIN fim.agents ag ON a.agent_id = ag.id
        ORDER BY a.created_at DESC
        LIMIT :limit
    """), {"limit": limit})
    
    return [dict(row._mapping) for row in result.fetchall()]

@router.get("/reports/stats")
async def get_report_stats(db: AsyncSession = Depends(get_db)):
    """Get report statistics for dashboard"""
    from datetime import datetime, timedelta
    
    # Pending/Unreviewed count
    pending = await db.execute(text("SELECT COUNT(*) FROM fim.reports WHERE status IN ('pending', 'in_review')"))
    pending_count = pending.scalar()
    
    # Missing reports (last 7 days)
    today = datetime.now().date()
    missing_count = 0
    
    for i in range(7):
        check_date = today - timedelta(days=i)
        res = await db.execute(text("SELECT 1 FROM fim.reports WHERE report_date = :date"), {"date": check_date})
        if not res.scalar():
            missing_count += 1
            
    return {
        "pending_review": pending_count,
        "missing_reports": missing_count
    }


@router.get("/trends")
async def get_dashboard_trends(
    days: int = 30,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Get daily alert and change trends for dashboard charts."""
    from datetime import datetime, timedelta

    cutoff = (datetime.now() - timedelta(days=days)).date()

    # Alerts per day
    alerts_trend = await db.execute(text("""
        SELECT DATE(detected_at) as day,
               COUNT(*) as total,
               COUNT(*) FILTER (WHERE severity = 'critical') as critical,
               COUNT(*) FILTER (WHERE severity = 'high') as high,
               COUNT(*) FILTER (WHERE severity = 'medium') as medium
        FROM fim.alerts
        WHERE DATE(detected_at) >= :cutoff
        GROUP BY DATE(detected_at)
        ORDER BY day
    """), {"cutoff": cutoff})
    alerts_by_day = []
    for row in alerts_trend.fetchall():
        alerts_by_day.append({
            "day": str(row.day), "total": row.total,
            "critical": row.critical, "high": row.high, "medium": row.medium
        })

    # Scans per day
    scans_trend = await db.execute(text("""
        SELECT DATE(completed_at) as day,
               COUNT(*) as scans,
               COALESCE(SUM(files_scanned), 0) as files_scanned,
               COALESCE(SUM(files_changed), 0) as changes
        FROM fim.scans
        WHERE DATE(completed_at) >= :cutoff
        GROUP BY DATE(completed_at)
        ORDER BY day
    """), {"cutoff": cutoff})
    scans_by_day = []
    for row in scans_trend.fetchall():
        scans_by_day.append({
            "day": str(row.day), "scans": row.scans,
            "files_scanned": int(row.files_scanned), "changes": int(row.changes)
        })

    # Alert status distribution (for donut)
    status_dist = await db.execute(text("""
        SELECT status, COUNT(*) as count FROM fim.alerts GROUP BY status
    """))
    status_distribution = [{"name": row.status, "value": row.count} for row in status_dist.fetchall()]

    # Severity distribution (for donut)
    sev_dist = await db.execute(text("""
        SELECT severity, COUNT(*) as count FROM fim.alerts WHERE status = 'open' GROUP BY severity
    """))
    severity_distribution = [{"name": row.severity, "value": row.count} for row in sev_dist.fetchall()]

    return {
        "alerts_by_day": alerts_by_day,
        "scans_by_day": scans_by_day,
        "status_distribution": status_distribution,
        "severity_distribution": severity_distribution,
    }


@router.get("/agents/details")
async def get_agent_details(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Detailed agent health with scan history."""
    result = await db.execute(text("""
        SELECT a.id, a.hostname, a.ip_address, a.status, a.is_healthy,
               a.last_heartbeat, a.os_type, a.os_version, a.tags,
               (SELECT COUNT(*) FROM fim.scans s WHERE s.agent_id = a.id) as total_scans,
               (SELECT MAX(completed_at) FROM fim.scans s WHERE s.agent_id = a.id) as last_scan,
               (SELECT files_scanned FROM fim.scans s WHERE s.agent_id = a.id ORDER BY completed_at DESC LIMIT 1) as last_files_scanned,
               (SELECT files_changed FROM fim.scans s WHERE s.agent_id = a.id ORDER BY completed_at DESC LIMIT 1) as last_files_changed,
               (SELECT COUNT(*) FROM fim.alerts al WHERE al.agent_id = a.id AND al.status = 'open') as open_alerts
        FROM fim.agents a
        ORDER BY a.hostname
    """))
    agents = []
    for r in result.fetchall():
        agents.append({
            "id": str(r.id), "hostname": r.hostname, "ip_address": r.ip_address,
            "status": r.status, "is_healthy": r.is_healthy,
            "last_heartbeat": r.last_heartbeat.isoformat() if r.last_heartbeat else None,
            "os_type": r.os_type, "os_version": r.os_version,
            "tags": r.tags or [],
            "total_scans": r.total_scans, "last_scan": r.last_scan.isoformat() if r.last_scan else None,
            "last_files_scanned": r.last_files_scanned or 0,
            "last_files_changed": r.last_files_changed or 0,
            "open_alerts": r.open_alerts,
        })
    return {"agents": agents}
