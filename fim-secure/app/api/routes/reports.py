from fastapi import APIRouter, Depends, HTTPException, Response
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func, text
from datetime import date, datetime, timedelta
from typing import Optional, List
import uuid

from app.core.database import get_db
from app.models.daily_report import DailyReport, ReportChange
from app.schemas.daily_report import (
    DailyReportResponse, 
    DailyReportDetail,
    GenerateReportRequest,
    UpdateNotesRequest,
    UpdateStatusRequest,
    DailyReportSummary
)
from app.core.security import get_current_user
from app.models.models import User

router = APIRouter()


@router.post("/generate")
async def generate_daily_report(
    request: GenerateReportRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Generate daily report for specified date (defaults to yesterday)"""
    report_date = request.report_date or (datetime.now() - timedelta(days=1)).date()
    
    # Check if report already exists
    result = await db.execute(
        select(DailyReport).where(DailyReport.report_date == report_date)
    )
    existing = result.scalar_one_or_none()
    
    if existing:
        raise HTTPException(
            status_code=400, 
            detail=f"Report already exists for {report_date}. Delete it first or use a different date."
        )
    
    # Fetch all alerts for this date
    query = text("""
        SELECT 
            a.id, a.agent_id, a.file_path, a.alert_type, a.severity,
            a.previous_state, a.current_state, a.detected_at,
            ag.hostname
        FROM fim.alerts a
        LEFT JOIN fim.agents ag ON a.agent_id = ag.id
        WHERE DATE(a.created_at) = :report_date
        ORDER BY ag.hostname, a.file_path
    """)
    
    result = await db.execute(query, {"report_date": report_date})
    alerts = result.fetchall()
    
    # Allow empty reports (no alerts found)
    agent_set = set()
    added_count = 0
    removed_count = 0
    changed_count = 0
    
    if alerts:
        for alert in alerts:
            if alert.hostname:
                agent_set.add(alert.hostname)
            
            # Determine change type from alert_type
            alert_type = alert.alert_type or ''
            if 'created' in alert_type.lower() or 'added' in alert_type.lower() or 'new' in alert_type.lower():
                added_count += 1
            elif 'deleted' in alert_type.lower() or 'removed' in alert_type.lower():
                removed_count += 1
            elif 'modified' in alert_type.lower() or 'changed' in alert_type.lower():
                changed_count += 1
            else:
                # Default to changed if unclear
                changed_count += 1
    
    total_changes = added_count + removed_count + changed_count
    
    # Create daily report (even if no alerts)
    daily_report = DailyReport(
        id=uuid.uuid4(),
        report_type='daily',
        report_date=report_date,
        date_from=report_date,
        date_to=report_date,
        agent_list=list(agent_set) if agent_set else [],
        total_added=added_count,
        total_removed=removed_count,
        total_changed=changed_count,
        total_changes=total_changes,
        total_servers=len(agent_set),
        status='pending',
        generated_by=current_user.id
    )
    db.add(daily_report)
    await db.flush()
    
    # Create report_changes entries (if any alerts exist)
    if alerts:
        for alert in alerts:
            if alert.change_type in ('created', 'added'):
                change_type = 'added'
            elif alert.change_type in ('deleted', 'removed'):
                change_type = 'removed'
            elif alert.change_type in ('modified', 'changed'):
                change_type = 'changed'
            else:
                change_type = 'changed'
            
            # Extract mtime and hash from JSONB states
            previous_state = alert.previous_state or {}
            current_state = alert.current_state or {}
            
            # Handle JSONB data
            if isinstance(previous_state, str):
                import json
                previous_state = json.loads(previous_state)
            if isinstance(current_state, str):
                import json
                current_state = json.loads(current_state)
            
            baseline_mtime = None
            current_mtime = None
            baseline_hash = None
            current_hash = None
            
            if previous_state:
                baseline_mtime_str = previous_state.get('mtime')
                if baseline_mtime_str:
                    try:
                        baseline_mtime = datetime.fromisoformat(baseline_mtime_str.replace('Z', '+00:00'))
                    except:
                        pass
                baseline_hash = previous_state.get('hash') or previous_state.get('checksum')
            
            if current_state:
                current_mtime_str = current_state.get('mtime')
                if current_mtime_str:
                    try:
                        current_mtime = datetime.fromisoformat(current_mtime_str.replace('Z', '+00:00'))
                    except:
                        pass
                current_hash = current_state.get('hash') or current_state.get('checksum')
            
            report_change = ReportChange(
                id=uuid.uuid4(),
                report_id=daily_report.id,
                alert_id=alert.id,
                agent_hostname=alert.hostname,
                file_path=alert.file_path,
                change_type=change_type,
                severity=alert.severity,
                baseline_mtime=baseline_mtime,
                current_mtime=current_mtime or alert.detected_at,
                baseline_hash=baseline_hash,
                current_hash=current_hash
            )
            db.add(report_change)
    
    await db.commit()
    await db.refresh(daily_report)
    
    message = f"Report generated successfully for {report_date}"
    if total_changes == 0:
        message += " (no file changes detected)"
    
    return {
        "message": message,
        "report_id": str(daily_report.id),
        "report_date": str(report_date),
        "total_changes": total_changes,
        "total_servers": len(agent_set),
        "breakdown": {
            "added": added_count,
            "removed": removed_count,
            "changed": changed_count
        }
    }


@router.get("/", response_model=List[DailyReportResponse])
async def list_reports(
    skip: int = 0,
    limit: int = 30,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """List all daily reports"""
    result = await db.execute(
        select(DailyReport)
        .where(DailyReport.report_type == 'daily')
        .order_by(DailyReport.report_date.desc())
        .offset(skip)
        .limit(limit)
    )
    reports = result.scalars().all()
    
    response = []
    for report in reports:
        response.append(
            DailyReportResponse(
                id=report.id,
                report_date=report.report_date,
                agents=report.agent_list or [],
                summary=DailyReportSummary(
                    added_files=report.total_added or 0,
                    removed_files=report.total_removed or 0,
                    changed_files=report.total_changed or 0
                ),
                status=report.status,
                total_changes=report.total_changes or 0,
                analyst_notes=report.analyst_notes,
                created_at=report.created_at,
                reviewed_by=report.reviewed_by
            )
        )
    
    return response


@router.get("/{report_date}", response_model=DailyReportDetail)
async def get_daily_report(
    report_date: date,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Get detailed daily report"""
    result = await db.execute(
        select(DailyReport).where(
            DailyReport.report_date == report_date,
            DailyReport.report_type == 'daily'
        )
    )
    report = result.scalar_one_or_none()
    
    if not report:
        raise HTTPException(status_code=404, detail=f"Report not found for {report_date}")
    
    # Fetch changes
    result = await db.execute(
        select(ReportChange)
        .where(ReportChange.report_id == report.id)
        .order_by(ReportChange.change_type, ReportChange.file_path)
    )
    changes = result.scalars().all()
    
    # Group changes by type
    added = [c.file_path for c in changes if c.change_type == 'added']
    removed = [c.file_path for c in changes if c.change_type == 'removed']
    changed_list = [c.file_path for c in changes if c.change_type == 'changed']
    
    # Detailed information for changed files
    details = []
    for change in changes:
        if change.change_type == 'changed' and change.baseline_mtime and change.current_mtime:
            details.append({
                "file_path": change.file_path,
                "baseline_mtime": change.baseline_mtime.strftime('%Y-%m-%d %H:%M:%S'),
                "current_mtime": change.current_mtime.strftime('%Y-%m-%d %H:%M:%S')
            })
    
    return DailyReportDetail(
        id=report.id,
        report_date=report.report_date,
        agents=report.agent_list or [],
        summary=DailyReportSummary(
            added_files=report.total_added or 0,
            removed_files=report.total_removed or 0,
            changed_files=report.total_changed or 0
        ),
        status=report.status,
        total_changes=report.total_changes or 0,
        analyst_notes=report.analyst_notes,
        created_at=report.created_at,
        reviewed_by=report.reviewed_by,
        changes={
            "added": added,
            "removed": removed,
            "changed": changed_list
        },
        details=details
    )


@router.get("/{report_date}/export")
async def export_report(
    report_date: date,
    format: str = "txt",
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Export report in text format"""
    result = await db.execute(
        select(DailyReport).where(
            DailyReport.report_date == report_date,
            DailyReport.report_type == 'daily'
        )
    )
    report = result.scalar_one_or_none()
    
    if not report:
        raise HTTPException(status_code=404, detail=f"Report not found for {report_date}")
    
    result = await db.execute(
        select(ReportChange)
        .where(ReportChange.report_id == report.id)
        .order_by(ReportChange.change_type, ReportChange.file_path)
    )
    changes = result.scalars().all()
    
    if format == "txt":
        content = generate_text_report(report, changes)
        return Response(
            content=content,
            media_type="text/plain",
            headers={
                "Content-Disposition": f"attachment; filename=FIM-report-{report_date}.txt"
            }
        )
    
    raise HTTPException(status_code=400, detail="Format not supported")


def generate_text_report(report: DailyReport, changes: List[ReportChange]) -> str:
    """Generate text report matching your exact format"""
    lines = []
    
    # Agent list
    if report.agent_list:
        for agent in report.agent_list:
            lines.append(agent)
        lines.append("")
    else:
        lines.append("No agents reported changes")
        lines.append("")
    
    # Summary
    lines.append("Summary:")
    lines.append(f"Added files: {report.total_added or 0}")
    lines.append(f"Removed files: {report.total_removed or 0}")
    lines.append(f"Changed files: {report.total_changed or 0}")
    lines.append("")
    
    # Added files
    added = [c for c in changes if c.change_type == 'added']
    for change in added:
        lines.append(f"added: '{change.file_path}'")
    
    # Removed files
    removed = [c for c in changes if c.change_type == 'removed']
    for change in removed:
        lines.append(f"removed: '{change.file_path}'")
    
    # Changed files
    changed = [c for c in changes if c.change_type == 'changed']
    for change in changed:
        lines.append(f"changed: '{change.file_path}'")
    
    if changed:
        lines.append("")
        lines.append("Detailed information about changes:")
        for change in changed:
            lines.append(f"Directory: '{change.file_path}'")
            if change.baseline_mtime and change.current_mtime:
                baseline = change.baseline_mtime.strftime('%Y-%m-%d %H:%M:%S')
                current = change.current_mtime.strftime('%Y-%m-%d %H:%M:%S')
                lines.append(f"Mtime : {baseline} , {current}")
            lines.append("")
    
    if not changes:
        lines.append("")
        lines.append("No file integrity changes detected on this date.")
    
    return "\n".join(lines)


@router.patch("/{report_id}/notes")
async def update_analyst_notes(
    report_id: str,
    request: UpdateNotesRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Add/update analyst notes for a report"""
    try:
        report_uuid = uuid.UUID(report_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid report ID format")
    
    result = await db.execute(
        select(DailyReport).where(DailyReport.id == report_uuid)
    )
    report = result.scalar_one_or_none()
    
    if not report:
        raise HTTPException(status_code=404, detail="Report not found")
    
    report.analyst_notes = request.analyst_notes
    report.reviewed_by = current_user.id
    report.updated_at = datetime.now()
    
    await db.commit()
    
    return {"message": "Notes updated successfully"}


@router.patch("/{report_id}/status")
async def update_report_status(
    report_id: str,
    request: UpdateStatusRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Update report status"""
    try:
        report_uuid = uuid.UUID(report_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid report ID format")
    
    result = await db.execute(
        select(DailyReport).where(DailyReport.id == report_uuid)
    )
    report = result.scalar_one_or_none()
    
    if not report:
        raise HTTPException(status_code=404, detail="Report not found")
    
    report.status = request.status
    report.reviewed_by = current_user.id
    report.updated_at = datetime.now()
    
    if request.status in ['submitted', 'submitted_no_ticket']:
        report.submitted_by = current_user.id
        report.submitted_at = datetime.now()
    
    await db.commit()
    
    return {"message": f"Report status updated to {request.status}"}
