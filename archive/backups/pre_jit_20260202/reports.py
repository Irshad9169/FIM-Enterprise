from fastapi import APIRouter, Depends, HTTPException, Response
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func, text, or_
from datetime import date, datetime, timedelta
from typing import Optional, List, Dict, Any
import uuid
import json
import logging

from app.core.database import get_db
from app.models.daily_report import DailyReport, ReportChange
from app.schemas.daily_report import (
    DailyReportResponse, DailyReportDetail, GenerateReportRequest, 
    UpdateNotesRequest, UpdateStatusRequest, DailyReportSummary
)
from app.core.security import get_current_user
from app.models.models import User
from app.services.ticket_linker import TicketLinkerService

logger = logging.getLogger(__name__)
router = APIRouter()

async def find_report(db, report_id_or_date):
    try:
        uid = uuid.UUID(report_id_or_date)
        res = await db.execute(select(DailyReport).where(DailyReport.id == uid))
        return res.scalar_one_or_none()
    except:
        res = await db.execute(select(DailyReport).where(func.cast(DailyReport.report_date, text('text')) == report_id_or_date))
        return res.scalar_one_or_none()

@router.post("/generate")
async def generate_daily_report(request: GenerateReportRequest, db: AsyncSession = Depends(get_db), u: User = Depends(get_current_user)):
    try:
        report_date = request.report_date or datetime.now().date()
        res = await db.execute(select(DailyReport).where(DailyReport.report_date == report_date))
        if res.scalar_one_or_none(): raise HTTPException(400, "Report already exists")
        
        query = text("SELECT a.id, a.file_path, a.alert_type, a.severity, a.previous_state, a.current_state, a.detected_at, ag.hostname "
                     "FROM fim.alerts a LEFT JOIN fim.agents ag ON a.agent_id = ag.id WHERE DATE(a.created_at) = :d")
        res = await db.execute(query, {"d": report_date})
        alerts = res.fetchall()

        report_id = uuid.uuid4()
        agents = list(set([a.hostname for a in alerts if a.hostname]))
        
        report = DailyReport(
            id=report_id, report_date=report_date, agent_list=agents,
            total_added=len([a for a in alerts if 'created' in str(a.alert_type).lower()]),
            total_removed=len([a for a in alerts if 'deleted' in str(a.alert_type).lower()]),
            total_changed=len([a for a in alerts if 'modified' in str(a.alert_type).lower()]),
            total_changes=len(alerts), total_servers=len(agents), status='pending',
            generated_by=u.id
        )
        db.add(report)
        await db.flush()

        for a in alerts:
            try:
                p = json.loads(a.previous_state) if isinstance(a.previous_state, str) else (a.previous_state or {})
                c = json.loads(a.current_state) if isinstance(a.current_state, str) else (a.current_state or {})
                change = ReportChange(
                    id=uuid.uuid4(), report_id=report_id, alert_id=a.id, agent_hostname=a.hostname or 'unknown',
                    file_path=a.file_path or 'unknown', change_type='added' if 'created' in str(a.alert_type).lower() else 'changed',
                    severity=a.severity or 'medium', current_mtime=a.detected_at,
                    baseline_hash=p.get('hash'), current_hash=c.get('hash'),
                    baseline_size=p.get('size'), current_size=c.get('size'),
                    baseline_mtime=datetime.fromisoformat(str(p['mtime']).replace('Z', '+00:00')) if p.get('mtime') else None
                )
                db.add(change)
            except: continue

        # --- JIT CORRELATION ---
        try:
            await TicketLinkerService.correlate_report(report_id, agents, u.username, db)
        except Exception as e:
            logger.error(f"JIT Ticket Correlation failed: {e}")

        await db.commit()
        return {"message": "Success", "report_id": str(report_id)}
    except Exception as e:
        await db.rollback()
        logger.error(f"Generation failed: {e}")
        raise HTTPException(500, str(e))

@router.get("", response_model=List[DailyReportResponse])
async def list_reports(db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(DailyReport).order_by(DailyReport.report_date.desc()))
    return [DailyReportResponse(
        id=r.id, report_date=r.report_date, agents=r.agent_list or [],
        summary=DailyReportSummary(added_files=r.total_added, removed_files=r.total_removed, changed_files=r.total_changed),
        status=r.status, total_changes=r.total_changes, created_at=r.created_at
    ) for r in result.scalars().all()]

@router.get("/{report_id_or_date}/export")
async def export_report(report_id_or_date: str, db: AsyncSession = Depends(get_db)):
    r = await find_report(db, report_id_or_date)
    if not r: raise HTTPException(404)
    res_c = await db.execute(select(ReportChange).where(ReportChange.report_id == r.id))
    changes = res_c.scalars().all()
    lines = [f"FIM Report: {r.report_date}", "="*20, ""]
    for c in changes:
        lines.append(f"[{c.agent_hostname}] {c.change_type.upper()}: {c.file_path}")
    return Response("\n".join(lines), media_type="text/plain")

@router.get("/{id_or_date}", response_model=DailyReportDetail)
async def get_report(id_or_date: str, db: AsyncSession = Depends(get_db)):
    r = await find_report(db, id_or_date)
    if not r: raise HTTPException(404, "Report not found")
    
    res_c = await db.execute(select(ReportChange).where(ReportChange.report_id == r.id))
    changes = res_c.scalars().all()
    
    # FETCH LINKED TICKETS
    res_t = await db.execute(text("SELECT source, external_id, summary, url, agent_hostname FROM fim.report_tickets WHERE report_id = :rid"), {"rid": r.id})
    tickets = [dict(row._mapping) for row in res_t.fetchall()]
    
    return {
        "id": r.id, "report_date": r.report_date, "agents": r.agent_list or [], "status": r.status,
        "summary": {"added_files": r.total_added, "removed_files": r.total_removed, "changed_files": r.total_changed},
        "total_changes": r.total_changes, "created_at": r.created_at,
        "changes": {"added": [c.file_path for c in changes if c.change_type == 'added'], "removed": [c.file_path for c in changes if c.change_type == 'removed'], "changed": [c.file_path for c in changes if c.change_type == 'changed']},
        "details": [{"file_path": c.file_path, "agent_hostname": c.agent_hostname, "baseline_hash": c.baseline_hash, "current_hash": c.current_hash, "baseline_size": c.baseline_size, "current_size": c.current_size, "baseline_mtime": c.baseline_mtime.isoformat() if c.baseline_mtime else None, "current_mtime": c.current_mtime.isoformat() if c.current_mtime else None} for c in changes],
        "linked_tickets": tickets
    }

@router.delete("/{report_id}")
async def delete_report(report_id: str, db: AsyncSession = Depends(get_db)):
    r = await find_report(db, report_id)
    if not r: raise HTTPException(404)
    await db.execute(text("DELETE FROM fim.report_changes WHERE report_id = :id"), {"id": r.id})
    await db.execute(text("DELETE FROM fim.report_tickets WHERE report_id = :id"), {"id": r.id})
    await db.execute(text("DELETE FROM fim.reports WHERE id = :id"), {"id": r.id})
    await db.commit()
    return {"message": "Deleted"}

@router.patch("/{report_id}/status")
async def update_status(report_id: str, req: UpdateStatusRequest, db: AsyncSession = Depends(get_db)):
    r = await find_report(db, report_id)
    if not r: raise HTTPException(404)
    r.status = req.status
    await db.commit()
    return {"message": "updated"}
