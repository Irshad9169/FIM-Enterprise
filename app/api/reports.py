"""
Reports API — full workflow, aligned to real fim.* schema
Status values (DB constraint): pending / in_review / reviewed / submitted / submitted_no_ticket
"""
from app.core.rbac import admin_only
from fastapi import APIRouter, Depends, HTTPException, Response, Request
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func, text
from datetime import datetime
from typing import List, Dict, Tuple, Set, Optional, List, Optional
import uuid
import json
import logging

from app.core.database import get_db
from app.models.daily_report import DailyReport, ReportChange, ReportAgent, ReportTicket
from app.schemas.daily_report import (
    DailyReportResponse, DailyReportDetail, DailyReportSummary,
    GenerateReportRequest, UpdateNotesRequest, UpdateStatusRequest,
    UpdateAgentRequest, SubmitAgentRequest, LinkChangeRequest,
    PublishReportRequest, ReportAgentSchema, ReportChangeDetail,
    ReportTicketSchema,
)
from app.core.security import get_current_user
from app.models.models import User
from app.services.ticket_linker import TicketLinkerService
from app.services.audit_service import AuditService

logger = logging.getLogger(__name__)
router = APIRouter()

# Valid status values enforced by DB CHECK constraint
VALID_STATUSES = {"pending", "in_review", "reviewed", "submitted", "submitted_no_ticket"}


# ─────────────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────────────

def _client_ip(request: Request) -> str:
    """Extract client IP from request, respecting X-Forwarded-For."""
    forwarded = request.headers.get("x-forwarded-for")
    if forwarded:
        return forwarded.split(",")[0].strip()
    return request.client.host if request.client else ""


async def find_report(db: AsyncSession, report_id_or_date: str) -> Optional[DailyReport]:
    try:
        uid = uuid.UUID(report_id_or_date)
        res = await db.execute(select(DailyReport).where(DailyReport.id == uid))
        return res.scalar_one_or_none()
    except ValueError:
        res = await db.execute(
            select(DailyReport).where(
                func.cast(DailyReport.report_date, text("text")) == report_id_or_date
            )
        )
        return res.scalar_one_or_none()


def _change_to_schema(c: ReportChange) -> ReportChangeDetail:
    return ReportChangeDetail(
        id=str(c.id),
        file_path=c.file_path or "",
        agent_hostname=c.agent_hostname,
        change_type=c.change_type,
        severity=c.severity,
        baseline_hash=c.baseline_hash,
        current_hash=c.current_hash,
        baseline_size=c.baseline_size,
        current_size=c.current_size,
        baseline_mtime=c.baseline_mtime.isoformat() if c.baseline_mtime else None,
        current_mtime=c.current_mtime.isoformat() if c.current_mtime else None,
        external_ticket_id=c.external_ticket_id,
        linked_rt_tickets=c.linked_rt_tickets or [],
        matched_rt_tickets=c.matched_rt_tickets,
        rt_ticket_manually_added=c.rt_ticket_manually_added or False,
        analyst_notes=c.analyst_notes,
        is_known_change=c.is_known_change or False,
        is_verified=c.is_verified or False,
        requires_investigation=c.requires_investigation or False,
        audit_uid=c.audit_uid,
        audit_process=c.audit_process,
        audit_command=c.audit_command,
        content_diff=c.content_diff,
    )


def _submitted_count(report: DailyReport) -> int:
    """Derive submitted count from submitted_agents array."""
    return len(report.submitted_agents or [])


async def _build_report_agents(report_id: uuid.UUID, db: AsyncSession) -> List[ReportAgentSchema]:
    ra_res = await db.execute(
        select(ReportAgent).where(ReportAgent.report_id == report_id)
    )
    agent_rows = ra_res.scalars().all()
    result = []

    for ag in agent_rows:
        # Changes for this agent
        ch_res = await db.execute(
            select(ReportChange).where(
                ReportChange.report_id == report_id,
                ReportChange.agent_hostname == ag.agent_hostname,
            )
        )
        changes = [_change_to_schema(c) for c in ch_res.scalars().all()]

        # Tickets from report_tickets for this agent
        tk_res = await db.execute(
            select(ReportTicket).where(
                ReportTicket.report_id == report_id,
                ReportTicket.agent_hostname == ag.agent_hostname,
            )
        )
        tickets = [
            ReportTicketSchema(
                id=str(t.id), source=t.source, external_id=t.external_id,
                summary=t.summary, url=t.url, is_linked=t.is_linked or False,
            )
            for t in tk_res.scalars().all()
        ]

        result.append(ReportAgentSchema(
            id=str(ag.id),
            agent_hostname=ag.agent_hostname,
            ip_address=ag.ip_address,
            correlated_rt=ag.correlated_rt,
            correlated_cmr=ag.correlated_cmr,
            manual_rt=ag.manual_rt,
            correlation_note=ag.correlation_note,
            status=ag.status,
            is_skipped=ag.is_skipped or False,
            skip_reason=ag.skip_reason,
            correlated_at=ag.correlated_at,
            submitted_at=ag.submitted_at,
            changes=changes,
            tickets=tickets,
        ))
    return result


# ─────────────────────────────────────────────────────────────────────────────
# List & Generate
# ─────────────────────────────────────────────────────────────────────────────

@router.get("", response_model=List[DailyReportResponse])
async def list_reports(db: AsyncSession = Depends(get_db)):
    result = await db.execute(
        select(DailyReport).order_by(DailyReport.report_date.desc())
    )
    rows = result.scalars().all()
    return [
        DailyReportResponse(
            id=r.id,
            report_date=r.report_date,
            agents=r.agent_list or [],
            summary=DailyReportSummary(
                added_files=r.total_added or 0,
                removed_files=r.total_removed or 0,
                changed_files=r.total_changed or 0,
            ),
            status=r.status,
            total_changes=r.total_changes or 0,
            analyst_notes=r.analyst_notes,
            created_at=r.created_at,
            agents_total=r.agents_total or len(r.agent_list or []),
            agents_submitted=_submitted_count(r),
            rt_ticket_id=r.rt_ticket_id,
            published_at=r.published_at,
        )
        for r in rows
    ]


@router.post("/generate")
async def generate_daily_report(
    req: GenerateReportRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    try:
        report_date = req.report_date or datetime.now().date()

        existing = await db.execute(
            select(DailyReport).where(DailyReport.report_date == report_date)
        )
        if existing.scalar_one_or_none():
            raise HTTPException(400, "Report already exists for this date")

        # Fetch alerts for the day (use detected_at for time range)
        res = await db.execute(text("""
            SELECT a.id, a.file_path, a.alert_type, a.severity,
                   a.previous_state, a.current_state, a.detected_at,
                   a.audit_uid, a.audit_process, a.audit_command,
                   ag.hostname, ag.ip_address
            FROM fim.alerts a
            LEFT JOIN fim.agents ag ON a.agent_id = ag.id
            WHERE DATE(a.detected_at) = :d AND a.status != 'false_positive'
            ORDER BY ag.hostname, a.detected_at
        """), {"d": report_date})
        alerts = res.fetchall()

        report_id = uuid.uuid4()
        agents    = list({a.hostname for a in alerts if a.hostname})

        report = DailyReport(
            id=report_id,
            report_date=report_date,
            agent_list=agents,
            submitted_agents=[],
            total_added=sum(1 for a in alerts if "created" in str(a.alert_type).lower()),
            total_removed=sum(1 for a in alerts if "deleted" in str(a.alert_type).lower()),
            total_changed=sum(1 for a in alerts if "modified" in str(a.alert_type).lower()),
            total_changes=len(alerts),
            total_servers=len(agents),
            agents_total=len(agents),
            status="pending",
            generated_by=current_user.id,
        )
        db.add(report)
        await db.flush()

        for a in alerts:
            try:
                p = json.loads(a.previous_state) if isinstance(a.previous_state, str) else (a.previous_state or {})
                c = json.loads(a.current_state)  if isinstance(a.current_state, str)  else (a.current_state or {})
                change = ReportChange(
                    id=uuid.uuid4(),
                    report_id=report_id,
                    alert_id=a.id,
                    agent_hostname=a.hostname or "unknown",
                    file_path=a.file_path or "unknown",
                    change_type=(
                        "added" if "created" in str(a.alert_type).lower() else
                        "removed" if "deleted" in str(a.alert_type).lower() else
                        "changed"
                    ),
                    severity=a.severity or "medium",
                    current_mtime=a.detected_at,
                    baseline_hash=p.get("hash"),
                    current_hash=c.get("hash"),
                    baseline_size=p.get("size"),
                    current_size=c.get("size"),
                    baseline_mtime=(
                        datetime.fromisoformat(str(p["mtime"]).replace("Z", "+00:00"))
                        if p.get("mtime") else None
                    ),
                    audit_uid=a.audit_uid,
                    audit_process=a.audit_process,
                    audit_command=a.audit_command,
                    content_diff=c.get("content_diff"),
                )
                db.add(change)
            except Exception:
                continue

        # Audit log: GENERATE_REPORT
        await AuditService.log(
            db, current_user.id, current_user.username, "GENERATE_REPORT",
            resource_type="report", resource_id=report_id,
            details={"date": str(report_date), "agents": len(agents), "alerts": len(alerts)},
            ip_address=_client_ip(request),
        )

        await db.commit()
        return {"message": "Success", "report_id": str(report_id), "agents": agents, "total_alerts": len(alerts)}

    except HTTPException:
        raise
    except Exception as e:
        await db.rollback()
        logger.error(f"generate_daily_report: {e}", exc_info=True)
        raise HTTPException(500, str(e))


# ─────────────────────────────────────────────────────────────────────────────
# Correlation — must come BEFORE the catch-all /{id_or_date}
# ─────────────────────────────────────────────────────────────────────────────

@router.post("/{report_id}/correlate")
async def correlate_report(
    report_id: str,
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Trigger RT + CMR correlation for all agents in a report."""
    r = await find_report(db, report_id)
    if not r:
        raise HTTPException(404, "Report not found")

    agent_list = r.agent_list or []
    if not agent_list:
        raise HTTPException(400, "Report has no agents to correlate")

    # Move status to in_review when correlation starts
    if r.status == "pending":
        r.status = "in_review"
        await db.flush()

    sso_token = request.headers.get("Authorization", "").replace("Bearer ", "")
    summary = await TicketLinkerService.correlate_all_agents(
        str(r.id), agent_list, sso_token, db
    )

    # Audit log: CORRELATE_REPORT
    await AuditService.log(
        db, current_user.id, current_user.username, "CORRELATE_REPORT",
        resource_type="report", resource_id=r.id,
        details={"agents": len(agent_list), "rt_found": summary.get("rt_found", 0), "cmr_found": summary.get("cmr_found", 0)},
        ip_address=_client_ip(request),
    )
    await db.commit()

    return {"message": "Correlation complete", "summary": summary}


@router.get("/{report_id}/agents/{hostname}/find-tickets")
async def find_tickets_for_agent(
    report_id: str,
    hostname: str,
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """On-demand RT + CMR search for a single agent hostname."""
    r = await find_report(db, report_id)
    if not r:
        raise HTTPException(404, "Report not found")

    sso_token = request.headers.get("Authorization", "").replace("Bearer ", "")
    tickets = await TicketLinkerService.find_tickets_for_agent(
        str(r.id), hostname, sso_token, db
    )
    return tickets


# ─────────────────────────────────────────────────────────────────────────────
# Per-agent workflow
# ─────────────────────────────────────────────────────────────────────────────

@router.patch("/{report_id}/agents/{hostname}")
async def update_agent(
    report_id: str,
    hostname: str,
    req: UpdateAgentRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    r = await find_report(db, report_id)
    if not r:
        raise HTTPException(404, "Report not found")

    res = await db.execute(
        select(ReportAgent).where(
            ReportAgent.report_id == r.id,
            ReportAgent.agent_hostname == hostname,
        )
    )
    agent = res.scalar_one_or_none()

    if not agent:
        # Auto-create if correlation hasn't run yet
        agent = ReportAgent(report_id=r.id, agent_hostname=hostname)
        db.add(agent)
        await db.flush()

    if req.manual_rt        is not None: agent.manual_rt        = req.manual_rt
    if req.correlated_rt    is not None: agent.correlated_rt    = req.correlated_rt
    if req.correlated_cmr   is not None: agent.correlated_cmr   = req.correlated_cmr
    if req.correlation_note is not None: agent.correlation_note = req.correlation_note
    if req.is_skipped       is not None:
        agent.is_skipped  = req.is_skipped
        agent.skip_reason = req.skip_reason
        if req.is_skipped and agent.status not in ("submitted",):
            agent.status  = "skipped"

    await db.commit()
    return {"message": "Agent updated"}


@router.post("/{report_id}/agents/{hostname}/submit")
async def submit_agent(
    report_id: str,
    hostname: str,
    req: SubmitAgentRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Mark an agent as reviewed and track it in submitted_agents[]."""
    r = await find_report(db, report_id)
    if not r:
        raise HTTPException(404, "Report not found")

    res = await db.execute(
        select(ReportAgent).where(
            ReportAgent.report_id == r.id,
            ReportAgent.agent_hostname == hostname,
        )
    )
    agent = res.scalar_one_or_none()
    if not agent:
        raise HTTPException(404, "Agent record not found — run Correlate All first")

    if req.rt_number: agent.manual_rt        = req.rt_number
    if req.note:      agent.correlation_note = req.note
    agent.status       = "submitted"
    agent.submitted_at = datetime.utcnow()

    # Track in report.submitted_agents[] (text array)
    current_submitted = list(r.submitted_agents or [])
    if hostname not in current_submitted:
        current_submitted.append(hostname)
        r.submitted_agents = current_submitted

    # Audit log: SUBMIT_AGENT
    await AuditService.log(
        db, current_user.id, current_user.username, "SUBMIT_AGENT",
        resource_type="report", resource_id=r.id,
        details={"hostname": hostname, "rt_number": req.rt_number, "report_date": str(r.report_date)},
        ip_address=_client_ip(request),
    )

    await db.commit()
    return {
        "message":         f"{hostname} submitted",
        "agents_submitted": len(r.submitted_agents or []),
        "agents_total":     r.agents_total or len(r.agent_list or []),
    }


# ─────────────────────────────────────────────────────────────────────────────
# Per-change linking
# ─────────────────────────────────────────────────────────────────────────────

@router.patch("/{report_id}/changes/{change_id}/link")
async def link_change(
    report_id: str,
    change_id: str,
    req: LinkChangeRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    Link a file change to an RT ticket.
    Uses existing columns: external_ticket_id, linked_rt_tickets[], rt_ticket_manually_added.
    If is_known_change=True, analyst_notes is required (enforced by DB CHECK).
    """
    try:
        cid = uuid.UUID(change_id)
    except ValueError:
        raise HTTPException(400, "Invalid change ID")

    res = await db.execute(select(ReportChange).where(ReportChange.id == cid))
    change = res.scalar_one_or_none()
    if not change:
        raise HTTPException(404, "Change not found")

    if req.rt_number:
        change.external_ticket_id       = req.rt_number
        change.rt_ticket_manually_added = True
        # Append to linked_rt_tickets array
        existing = list(change.linked_rt_tickets or [])
        if req.rt_number not in existing:
            existing.append(req.rt_number)
        change.linked_rt_tickets = existing

    if req.is_known_change is not None:
        if req.is_known_change and not (req.analyst_notes or change.analyst_notes):
            raise HTTPException(
                422,
                "analyst_notes is required when marking a change as known (DB constraint)"
            )
        change.is_known_change = req.is_known_change

    if req.analyst_notes is not None:
        change.analyst_notes = req.analyst_notes

    if req.requires_investigation is not None:
        change.requires_investigation = req.requires_investigation

    change.reviewed_at = datetime.utcnow()
    change.reviewed_by = current_user.id

    # Audit log: REVIEW_CHANGE
    await AuditService.log(
        db, current_user.id, current_user.username, "REVIEW_CHANGE",
        resource_type="change", resource_id=cid,
        details={
            "file_path": change.file_path,
            "rt_number": req.rt_number,
            "is_known_change": req.is_known_change,
            "requires_investigation": req.requires_investigation,
        },
        ip_address=_client_ip(request),
    )

    await db.commit()
    return {"message": "Change updated"}


# ─────────────────────────────────────────────────────────────────────────────
# Publish
# ─────────────────────────────────────────────────────────────────────────────

@router.post("/{report_id}/publish")
async def publish_report(
    report_id: str,
    req: PublishReportRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    Post the consolidated FIM summary to the daily RT review ticket.
    Sets report.status to 'submitted' (RT found) or 'submitted_no_ticket' (RT not found).
    Both are valid DB status values.
    """
    r = await find_report(db, report_id)
    if not r:
        raise HTTPException(404, "Report not found")

    ra_res = await db.execute(
        select(ReportAgent).where(ReportAgent.report_id == r.id)
    )
    agents = ra_res.scalars().all()

    if not req.force:
        not_submitted = [a for a in agents if a.status not in ("submitted", "skipped")]
        if not_submitted:
            raise HTTPException(
                400,
                f"{len(not_submitted)} agent(s) not yet submitted: "
                + ", ".join(a.agent_hostname for a in not_submitted),
            )

    # Build payload with full change details
    agents_data = []
    for ag in agents:
        # Fetch all changes for this agent
        changes_res = await db.execute(text("""
            SELECT file_path, change_type, severity,
                   baseline_hash, current_hash,
                   baseline_size, current_size,
                   analyst_notes, is_known_change,
                   requires_investigation
            FROM fim.report_changes
            WHERE report_id = :rid AND agent_hostname = :host
            ORDER BY file_path
        """), {"rid": str(r.id), "host": ag.agent_hostname})
        changes_rows = changes_res.fetchall()

        changes = []
        for ch in changes_rows:
            changes.append({
                "file_path":              ch.file_path,
                "change_type":            ch.change_type,
                "severity":               ch.severity,
                "baseline_hash":          ch.baseline_hash,
                "current_hash":           ch.current_hash,
                "baseline_size":          ch.baseline_size,
                "current_size":           ch.current_size,
                "analyst_notes":          ch.analyst_notes,
                "is_known_change":        ch.is_known_change,
                "requires_investigation": ch.requires_investigation,
            })

        agents_data.append({
            "agent_hostname":   ag.agent_hostname,
            "correlated_rt":    ag.correlated_rt,
            "correlated_cmr":   ag.correlated_cmr,
            "manual_rt":        ag.manual_rt,
            "correlation_note": ag.correlation_note,
            "status":           ag.status,
            "change_count":     len(changes),
            "changes":          changes,
        })

    sso_token = request.headers.get("Authorization", "").replace("Bearer ", "")
    result = await TicketLinkerService.publish_report(
        str(r.id), r.report_date, agents_data, sso_token,
        analyst_notes=r.analyst_notes or "",
    )

    # Use DB-valid status values from ticket_linker
    new_status = result.get("status_to_set", "submitted_no_ticket")
    r.status         = new_status
    r.submitted_at   = datetime.utcnow()
    r.submitted_by   = current_user.id
    r.rt_ticket_id   = result.get("ticket_id")
    r.rt_ticket_found = result["success"]
    if result["success"]:
        r.published_at = datetime.utcnow()
        r.published_by = current_user.id

    # Audit log: PUBLISH_REPORT
    await AuditService.log(
        db, current_user.id, current_user.username, "PUBLISH_REPORT",
        resource_type="report", resource_id=r.id,
        details={
            "report_date": str(r.report_date),
            "rt_ticket_id": result.get("ticket_id"),
            "success": result["success"],
            "agents_count": len(agents_data),
        },
        ip_address=_client_ip(request),
    )

    await db.commit()
    return result


# ─────────────────────────────────────────────────────────────────────────────
# Status & Notes
# ─────────────────────────────────────────────────────────────────────────────

@router.patch("/{report_id}/status")
async def update_status(
    report_id: str,
    req: UpdateStatusRequest,
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    if req.status not in VALID_STATUSES:
        raise HTTPException(400, f"Invalid status. Must be one of: {', '.join(sorted(VALID_STATUSES))}")
    r = await find_report(db, report_id)
    if not r:
        raise HTTPException(404, "Report not found")

    old_status = r.status
    r.status = req.status
    if req.status == "reviewed":
        r.reviewed_by = current_user.id

    # Audit log: UPDATE_REPORT_STATUS
    await AuditService.log(
        db, current_user.id, current_user.username, "UPDATE_REPORT_STATUS",
        resource_type="report", resource_id=r.id,
        details={"report_date": str(r.report_date), "old_status": old_status, "new_status": req.status},
        ip_address=_client_ip(request),
    )

    await db.commit()
    return {"message": "Status updated", "status": req.status}


@router.patch("/{report_id}/notes")
async def update_notes(
    report_id: str,
    req: UpdateNotesRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    r = await find_report(db, report_id)
    if not r:
        raise HTTPException(404, "Report not found")
    r.analyst_notes = req.analyst_notes
    await db.commit()
    return {"message": "Notes saved"}


# ─────────────────────────────────────────────────────────────────────────────
# Export
# ─────────────────────────────────────────────────────────────────────────────

@router.get("/{report_id_or_date}/export")
async def export_report(
    report_id_or_date: str,
    db: AsyncSession = Depends(get_db),
):
    """Export report as rich plaintext with full change details."""
    r = await find_report(db, report_id_or_date)
    if not r:
        raise HTTPException(404, "Report not found")

    ch_res = await db.execute(
        select(ReportChange).where(ReportChange.report_id == r.id)
    )
    changes = ch_res.scalars().all()

    ag_res = await db.execute(
        select(ReportAgent).where(ReportAgent.report_id == r.id)
    )
    agents = ag_res.scalars().all()

    by_host: dict = {}
    for c in changes:
        by_host.setdefault(c.agent_hostname or "unknown", []).append(c)

    from app.services.report_export import ReportExportService
    text = ReportExportService.build_text_report(r, agents, by_host)
    return Response(text, media_type="text/plain")


@router.get("/{report_id_or_date}/export/pdf")
async def export_report_pdf(
    report_id_or_date: str,
    db: AsyncSession = Depends(get_db),
):
    """Export report as a formatted PDF document."""
    r = await find_report(db, report_id_or_date)
    if not r:
        raise HTTPException(404, "Report not found")

    ch_res = await db.execute(
        select(ReportChange).where(ReportChange.report_id == r.id)
    )
    changes = ch_res.scalars().all()

    ag_res = await db.execute(
        select(ReportAgent).where(ReportAgent.report_id == r.id)
    )
    agents = ag_res.scalars().all()

    by_host: dict = {}
    for c in changes:
        by_host.setdefault(c.agent_hostname or "unknown", []).append(c)

    from app.services.report_export import ReportExportService
    pdf_bytes = ReportExportService.build_pdf_report(r, agents, by_host)

    filename = f"FIM-report-{r.report_date}.pdf"
    return Response(
        pdf_bytes,
        media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


# ─────────────────────────────────────────────────────────────────────────────
# Get (catch-all — must be LAST)
# ─────────────────────────────────────────────────────────────────────────────

@router.get("/{id_or_date}", response_model=DailyReportDetail)
async def get_report(
    id_or_date: str,
    db: AsyncSession = Depends(get_db),
):
    r = await find_report(db, id_or_date)
    if not r:
        raise HTTPException(404, "Report not found")

    ch_res = await db.execute(
        select(ReportChange).where(ReportChange.report_id == r.id)
    )
    changes       = ch_res.scalars().all()
    report_agents = await _build_report_agents(r.id, db)

    return DailyReportDetail(
        id=r.id,
        report_date=r.report_date,
        agents=r.agent_list or [],
        status=r.status,
        summary=DailyReportSummary(
            added_files=r.total_added or 0,
            removed_files=r.total_removed or 0,
            changed_files=r.total_changed or 0,
        ),
        total_changes=r.total_changes or 0,
        analyst_notes=r.analyst_notes,
        created_at=r.created_at,
        agents_total=r.agents_total or len(r.agent_list or []),
        agents_submitted=_submitted_count(r),
        submitted_agents=r.submitted_agents or [],
        rt_ticket_id=r.rt_ticket_id,
        published_at=r.published_at,
        correlation_run_at=r.correlation_run_at,
        changes={
            "added":   [c.file_path for c in changes if c.change_type == "added"],
            "removed": [c.file_path for c in changes if c.change_type == "removed"],
            "changed": [c.file_path for c in changes if c.change_type == "changed"],
        },
        details=[_change_to_schema(c) for c in changes],
        report_agents=report_agents,
    )


# ─────────────────────────────────────────────────────────────────────────────
# Delete
# ─────────────────────────────────────────────────────────────────────────────

@router.delete("/{report_id}")
async def delete_report(
    report_id: str,
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(admin_only),
):
    r = await find_report(db, report_id)
    if not r:
        raise HTTPException(404, "Report not found")

    report_date = str(r.report_date)
    rid = str(r.id)

    # Delete in dependency order
    await db.execute(text("DELETE FROM fim.report_agents  WHERE report_id = :id"), {"id": rid})
    await db.execute(text("DELETE FROM fim.report_tickets WHERE report_id = :id"), {"id": rid})
    # report_changes and correlation_groups cascade via FK
    await db.execute(text("DELETE FROM fim.reports        WHERE id        = :id"), {"id": rid})

    # Audit log: DELETE_REPORT
    await AuditService.log(
        db, current_user.id, current_user.username, "DELETE_REPORT",
        resource_type="report",
        details={"report_date": report_date, "report_id": rid},
        ip_address=_client_ip(request),
    )

    await db.commit()
    return {"message": "Report deleted"}


@router.post("/archive")
async def archive_old_reports(
    days: int = 90,
    request: Request = None,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Archive reports older than N days. Sets status to 'archived'."""
    if current_user.role != "admin":
        raise HTTPException(403, "Admin access required")

    from datetime import timedelta
    cutoff = (datetime.now() - timedelta(days=days)).date()

    result = await db.execute(text("""
        UPDATE fim.reports SET status = 'archived'
        WHERE report_date < :cutoff AND status != 'archived'
        RETURNING id
    """), {"cutoff": cutoff})
    archived = result.fetchall()

    if archived:
        await AuditService.log(
            db, current_user.id, current_user.username, "ARCHIVE_REPORTS",
            details={"count": len(archived), "older_than_days": days, "cutoff": str(cutoff)},
            ip_address=_client_ip(request) if request else "",
        )

    await db.commit()
    return {"archived": len(archived), "cutoff_date": str(cutoff)}


@router.get("/archived")
async def list_archived_reports(
    limit: int = 50,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """List archived reports."""
    result = await db.execute(text("""
        SELECT id, report_date, status, total_changes, total_servers,
               agents_total, rt_ticket_id
        FROM fim.reports
        WHERE status = 'archived'
        ORDER BY report_date DESC
        LIMIT :limit
    """), {"limit": limit})
    return {"reports": [dict(row._mapping) for row in result.fetchall()]}


@router.post("/{report_id}/unarchive")
async def unarchive_report(
    report_id: str,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Restore an archived report."""
    if current_user.role != "admin":
        raise HTTPException(403, "Admin access required")

    await db.execute(text("""
        UPDATE fim.reports SET status = 'submitted' WHERE id = :id AND status = 'archived'
    """), {"id": report_id})
    await db.commit()
    return {"message": "Report unarchived"}


async def _gather_compliance_data(db: AsyncSession, days: int, username: str) -> dict:
    """Shared data-gathering for every compliance report (PCI-DSS, SOX, ...) — same underlying facts, different framing/PDF per framework."""
    from datetime import timedelta

    end_date = datetime.now().date()
    start_date = end_date - timedelta(days=days)

    agents_r = await db.execute(text("""
        SELECT a.hostname, a.ip_address, a.status,
               (SELECT MAX(completed_at)::date FROM fim.scans s WHERE s.agent_id = a.id) as last_scan,
               (SELECT COUNT(*) FROM fim.alerts al WHERE al.agent_id = a.id AND al.status = 'open') as open_alerts
        FROM fim.agents a ORDER BY a.hostname
    """))
    agents = [{"hostname": r.hostname, "ip_address": r.ip_address, "status": r.status,
               "last_scan": str(r.last_scan) if r.last_scan else "N/A",
               "open_alerts": r.open_alerts} for r in agents_r.fetchall()]

    alerts_r = await db.execute(text("""
        SELECT COUNT(*) as total,
               COUNT(*) FILTER (WHERE severity = 'critical') as critical,
               COUNT(*) FILTER (WHERE severity = 'high') as high,
               COUNT(*) FILTER (WHERE severity = 'medium') as medium,
               COUNT(*) FILTER (WHERE severity = 'low') as low
        FROM fim.alerts WHERE DATE(detected_at) >= :start
    """), {"start": start_date})
    al = alerts_r.fetchone()

    scans_r = await db.execute(text("SELECT COUNT(*) FROM fim.scans WHERE DATE(completed_at) >= :start"), {"start": start_date})
    total_scans = scans_r.scalar() or 0

    reports_r = await db.execute(text("SELECT COUNT(*) FROM fim.reports WHERE report_date >= :start"), {"start": start_date})
    total_reports = reports_r.scalar() or 0

    return {
        "start_date": str(start_date), "end_date": str(end_date),
        "generated_by": username,
        "total_agents": len(agents), "agents": agents,
        "total_alerts": al.total, "total_scans": total_scans,
        "total_reports": total_reports,
        "severity_breakdown": {"critical": al.critical, "high": al.high, "medium": al.medium, "low": al.low},
    }


@router.get("/compliance/pci-dss")
async def generate_pci_compliance_report(
    days: int = 30,
    request: Request = None,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Generate PCI-DSS 11.5 compliance report PDF."""
    from app.services.compliance_report import ComplianceReportService
    from fastapi.responses import Response

    data = await _gather_compliance_data(db, days, current_user.username)
    pdf_bytes = ComplianceReportService.generate_pci_dss_report(data)

    return Response(
        content=pdf_bytes, media_type="application/pdf",
        headers={"Content-Disposition": f"attachment; filename=FIM-PCI-DSS-Compliance-{data['end_date']}.pdf"}
    )


@router.get("/compliance/sox")
async def generate_sox_compliance_report(
    days: int = 30,
    request: Request = None,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Generate SOX IT General Controls (Change Management) compliance report PDF."""
    from app.services.compliance_report import ComplianceReportService
    from fastapi.responses import Response

    data = await _gather_compliance_data(db, days, current_user.username)
    pdf_bytes = ComplianceReportService.generate_sox_report(data)

    return Response(
        content=pdf_bytes, media_type="application/pdf",
        headers={"Content-Disposition": f"attachment; filename=FIM-SOX-Compliance-{data['end_date']}.pdf"}
    )
