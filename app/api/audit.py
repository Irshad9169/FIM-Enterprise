from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import text
from typing import List, Optional, Dict, Any
from datetime import datetime
from pydantic import BaseModel

from app.core.database import get_db
from app.core.security import get_current_user
from app.core.time_utils import as_utc
from app.models.models import User

router = APIRouter()

class AuditLogResponse(BaseModel):
    id: str
    action: str
    details: Optional[Dict[str, Any]]
    username: Optional[str]
    ip_address: Optional[str]
    created_at: datetime

    class Config:
        from_attributes = True

@router.get("")
async def list_audit_logs(
    limit: int = 50,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    try:
        # Map timestamp to created_at for frontend compatibility
        query = text("""
            SELECT 
                a.id, 
                a.action, 
                a.details, 
                u.username, 
                a.ip_address, 
                a.timestamp as created_at
            FROM fim.audit_logs a
            LEFT JOIN fim.users u ON a.user_id = u.id
            ORDER BY a.timestamp DESC
            LIMIT :limit
        """)
        result = await db.execute(query, {"limit": limit})
        
        logs = []
        for row in result.fetchall():
            log = dict(row._mapping)
            # Ensure details is a dict if it's stored as JSONB
            if log['details'] is None:
                log['details'] = {}
            # Ensure id is string
            log['id'] = str(log['id'])
            log['created_at'] = as_utc(log['created_at'])
            logs.append(log)
            
        return logs
    except Exception as e:
        print(f"Audit log error: {e}")
        return []


@router.get("/export/csv")
async def export_audit_csv(
    days: int = 30,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Export audit logs as CSV."""
    if current_user.role not in ("admin", "auditor"):
        from fastapi import HTTPException
        raise HTTPException(403, "Admin or auditor access required")

    from fastapi.responses import Response
    import json as _json

    result = await db.execute(text("""
        SELECT a.action, u.username, a.ip_address, a.details,
               a.timestamp as created_at
        FROM fim.audit_logs a
        LEFT JOIN fim.users u ON a.user_id = u.id
        WHERE a.timestamp >= NOW() - INTERVAL ':days days'
        ORDER BY a.timestamp DESC
    """.replace(":days", str(int(days)))))
    rows = result.fetchall()

    lines = ["Timestamp,Action,Username,IP Address,Details"]
    for r in rows:
        details = _json.dumps(r.details) if r.details else ""
        details = details.replace('"', '""')
        lines.append(f'"{r.created_at}","{r.action}","{r.username}","{r.ip_address}","{details}"')

    return Response(
        content="\n".join(lines),
        media_type="text/csv",
        headers={"Content-Disposition": f"attachment; filename=fim-audit-logs-{days}d.csv"}
    )


@router.get("/export/pdf")
async def export_audit_pdf(
    days: int = 30,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Export audit logs as PDF."""
    if current_user.role not in ("admin", "auditor"):
        from fastapi import HTTPException
        raise HTTPException(403, "Admin or auditor access required")

    from app.services.report_export import ReportExportService
    from fastapi.responses import Response
    from reportlab.lib.pagesizes import letter, landscape
    from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer
    from reportlab.lib.styles import getSampleStyleSheet
    from reportlab.lib import colors
    import io
    import json as _json

    result = await db.execute(text("""
        SELECT a.action, u.username, a.ip_address, a.details,
               a.timestamp as created_at
        FROM fim.audit_logs a
        LEFT JOIN fim.users u ON a.user_id = u.id
        WHERE a.timestamp >= NOW() - INTERVAL ':days days'
        ORDER BY a.timestamp DESC
    """.replace(":days", str(int(days)))))
    rows = result.fetchall()

    buf = io.BytesIO()
    doc = SimpleDocTemplate(buf, pagesize=landscape(letter), topMargin=30, bottomMargin=30)
    styles = getSampleStyleSheet()
    elements = []

    elements.append(Paragraph("FIM Enterprise — Audit Log Report", styles["Title"]))
    elements.append(Paragraph(f"Last {days} days | Generated: {datetime.now().strftime('%Y-%m-%d %H:%M')}", styles["Normal"]))
    elements.append(Spacer(1, 20))

    table_data = [["Timestamp", "Action", "User", "IP Address", "Details"]]
    for r in rows:
        details = ""
        if r.details:
            d = r.details if isinstance(r.details, dict) else {}
            details = ", ".join(f"{k}={v}" for k, v in list(d.items())[:3])
        table_data.append([
            r.created_at.strftime("%Y-%m-%d %H:%M") if r.created_at else "",
            r.action or "", r.username or "", r.ip_address or "",
            Paragraph(details[:80], styles["Normal"]) if details else ""
        ])

    if len(table_data) > 1:
        t = Table(table_data, colWidths=[110, 120, 80, 90, 250])
        t.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#1e293b")),
            ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
            ("FONTSIZE", (0, 0), (-1, -1), 7),
            ("GRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#334155")),
            ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.HexColor("#0f172a"), colors.HexColor("#1e293b")]),
            ("TEXTCOLOR", (0, 1), (-1, -1), colors.HexColor("#e2e8f0")),
            ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ]))
        elements.append(t)
    else:
        elements.append(Paragraph("No audit logs found for this period.", styles["Normal"]))

    elements.append(Spacer(1, 20))
    elements.append(Paragraph(f"Total entries: {len(rows)}", styles["Normal"]))

    doc.build(elements)
    buf.seek(0)

    return Response(
        content=buf.read(),
        media_type="application/pdf",
        headers={"Content-Disposition": f"attachment; filename=fim-audit-log-{days}d.pdf"}
    )
