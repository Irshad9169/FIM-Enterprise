"""
Report Export Service — generates PDF and Text exports of FIM daily reports
"""
import io
import logging
from datetime import datetime
from typing import List, Dict, Optional

from reportlab.lib.pagesizes import letter
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.colors import HexColor, black, white
from reportlab.lib.units import inch
from reportlab.lib.enums import TA_LEFT, TA_CENTER
from reportlab.platypus import (
    SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle,
    Preformatted, HRFlowable
)

logger = logging.getLogger(__name__)


class ReportExportService:
    """Generates PDF and plaintext exports of FIM daily security reports."""

    # ── Text Export ───────────────────────────────────────────────────────

    @staticmethod
    def build_text_report(report, agents, changes_by_host: Dict[str, list]) -> str:
        """
        Build rich plaintext report matching the RT publish format.
        report: DailyReport ORM object
        agents: list of ReportAgent ORM objects
        changes_by_host: {hostname: [ReportChange, ...]}
        """
        lines = [
            f"FIM Daily Security Review — {report.report_date}",
            "=" * 70,
            f"Status    : {report.status.upper()}",
            f"Generated : {report.created_at.strftime('%Y-%m-%d %H:%M UTC') if report.created_at else 'N/A'}",
            f"RT Ticket : RT#{report.rt_ticket_id}" if report.rt_ticket_id else "RT Ticket : N/A",
            "",
            f"Total Agents: {report.agents_total or len(report.agent_list or [])}   |   "
            f"Total Changes: {report.total_changes or 0}",
            "-" * 70,
        ]

        # Build agent lookup
        agent_map = {a.agent_hostname: a for a in agents}

        for hostname in sorted(changes_by_host.keys()):
            host_changes = changes_by_host[hostname]
            ag = agent_map.get(hostname)

            # Agent header
            status = ag.status if ag else "pending"
            rt_num = (ag.manual_rt or ag.correlated_rt) if ag else None
            cmr_num = ag.correlated_cmr if ag else None
            note = ag.correlation_note if ag else None

            rt_display = f"RT#{rt_num}" if rt_num else "N/A"
            cmr_display = f"CMR#{cmr_num}" if cmr_num else "N/A"

            lines += [
                "",
                f"HOST: {hostname}",
                f"  Review Status : {status}",
                f"  Changes       : {len(host_changes)}",
                f"  RT Ticket     : {rt_display}",
                f"  CMR           : {cmr_display}",
            ]
            if note:
                lines.append(f"  Note          : {note}")

            # Change details
            if host_changes:
                lines.append("")
                lines.append(f"  {'Type':<10}  {'Severity':<8}  File Path")
                lines.append(f"  {'-'*10}  {'-'*8}  {'-'*50}")

                for c in host_changes:
                    ctype = (c.change_type or "unknown").upper()
                    severity = (c.severity or "medium").upper()
                    lines.append(f"  {ctype:<10}  {severity:<8}  {c.file_path}")

                    # Hash
                    bh = c.baseline_hash or ""
                    ch = c.current_hash or ""
                    if bh and ch and bh != ch:
                        lines.append(f"{'':14}Hash: {bh[:16]}... -> {ch[:16]}...")
                    elif ch and not bh:
                        lines.append(f"{'':14}Hash: N/A -> {ch[:16]}...")
                    elif bh and not ch:
                        lines.append(f"{'':14}Hash: {bh[:16]}... -> removed")

                    # Size
                    bs = c.baseline_size
                    cs = c.current_size
                    if cs is not None and bs is not None and bs != cs:
                        lines.append(f"{'':14}Size: {bs} -> {cs} bytes")
                    elif cs is not None and bs is None:
                        lines.append(f"{'':14}Size: N/A -> {cs} bytes")
                    elif bs is not None and cs is None:
                        lines.append(f"{'':14}Size: {bs} bytes -> removed")

                    # Mtime
                    bm = c.baseline_mtime
                    cm = c.current_mtime
                    if cm and not bm:
                        lines.append(f"{'':14}Mtime: N/A -> {cm.strftime('%Y-%m-%dT%H:%M:%S')}")
                    elif cm and bm and cm != bm:
                        lines.append(
                            f"{'':14}Mtime: {bm.strftime('%Y-%m-%dT%H:%M:%S')} -> "
                            f"{cm.strftime('%Y-%m-%dT%H:%M:%S')}"
                        )

                    # Analyst notes
                    if c.analyst_notes:
                        lines.append(f"{'':14}Note: {c.analyst_notes}")

                    # Flags
                    flags = []
                    if c.is_known_change:
                        flags.append("KNOWN")
                    if c.requires_investigation:
                        flags.append("INVESTIGATE")
                    if flags:
                        lines.append(f"{'':14}Flags: [{', '.join(flags)}]")

                    # RT link
                    if c.external_ticket_id:
                        lines.append(f"{'':14}Linked: RT#{c.external_ticket_id}")

            lines.append("")

        # Report-level analyst notes
        if report.analyst_notes:
            lines += [
                "-" * 70,
                "ANALYST NOTES:",
                report.analyst_notes,
                "",
            ]

        lines += [
            "-" * 70,
            "Generated by FIM Enterprise — automated security review system",
        ]
        return "\n".join(lines)

    # ── PDF Export ────────────────────────────────────────────────────────

    @staticmethod
    def build_pdf_report(report, agents, changes_by_host: Dict[str, list]) -> bytes:
        """
        Build a professional PDF report.
        Returns PDF bytes.
        """
        buf = io.BytesIO()

        doc = SimpleDocTemplate(
            buf, pagesize=letter,
            leftMargin=0.6 * inch, rightMargin=0.6 * inch,
            topMargin=0.6 * inch, bottomMargin=0.6 * inch,
            title=f"FIM Daily Security Review - {report.report_date}",
            author="FIM Enterprise",
        )

        # Styles
        styles = getSampleStyleSheet()
        styles.add(ParagraphStyle('ReportTitle',
            parent=styles['Title'], fontSize=18, spaceAfter=4,
            textColor=HexColor('#1e3a5f'), fontName='Helvetica-Bold'))
        styles.add(ParagraphStyle('ReportSub',
            parent=styles['Normal'], fontSize=10, spaceAfter=2,
            textColor=HexColor('#666666')))
        styles.add(ParagraphStyle('HostHeader',
            parent=styles['Heading2'], fontSize=12, spaceBefore=14, spaceAfter=4,
            textColor=HexColor('#1e3a5f'), fontName='Helvetica-Bold'))
        styles.add(ParagraphStyle('HostDetail',
            parent=styles['Normal'], fontSize=9, leading=12, spaceAfter=2,
            fontName='Helvetica', leftIndent=10))
        styles.add(ParagraphStyle('ChangeRow',
            parent=styles['Normal'], fontSize=8, leading=10, fontName='Courier',
            leftIndent=10, spaceAfter=1))
        styles.add(ParagraphStyle('ChangeMeta',
            parent=styles['Normal'], fontSize=7.5, leading=9.5, fontName='Courier',
            leftIndent=30, spaceAfter=1, textColor=HexColor('#555555')))
        styles.add(ParagraphStyle('SectionLine',
            parent=styles['Normal'], fontSize=9, spaceBefore=8, spaceAfter=4,
            fontName='Helvetica-Bold', textColor=HexColor('#333333')))
        styles.add(ParagraphStyle('NotesStyle',
            parent=styles['Normal'], fontSize=9, leading=12,
            fontName='Helvetica', leftIndent=10, spaceAfter=4,
            backColor=HexColor('#f8f9fa'), borderPadding=6,
            borderWidth=0.5, borderColor=HexColor('#dddddd')))
        styles.add(ParagraphStyle('Footer',
            parent=styles['Normal'], fontSize=7, textColor=HexColor('#999999'),
            alignment=TA_CENTER))

        story = []

        # ── Title ────────────────────────────────────────────────────────
        story.append(Paragraph(
            f"FIM Daily Security Review — {report.report_date}", styles['ReportTitle']))
        story.append(HRFlowable(
            width="100%", thickness=2, color=HexColor('#1e3a5f'),
            spaceBefore=2, spaceAfter=8))

        # ── Summary Table ────────────────────────────────────────────────
        rt_display = f"RT#{report.rt_ticket_id}" if report.rt_ticket_id else "N/A"
        created = report.created_at.strftime('%Y-%m-%d %H:%M UTC') if report.created_at else "N/A"
        total_agents = report.agents_total or len(report.agent_list or [])
        total_changes = report.total_changes or 0

        summary_data = [
            ["Status", report.status.upper(), "RT Ticket", rt_display],
            ["Generated", created, "Agents", str(total_agents)],
            ["Added", str(report.total_added or 0), "Total Changes", str(total_changes)],
            ["Removed", str(report.total_removed or 0), "Changed", str(report.total_changed or 0)],
        ]
        t = Table(summary_data, colWidths=[1.2 * inch, 2.2 * inch, 1.2 * inch, 2.2 * inch])
        t.setStyle(TableStyle([
            ('FONTNAME', (0, 0), (0, -1), 'Helvetica-Bold'),
            ('FONTNAME', (2, 0), (2, -1), 'Helvetica-Bold'),
            ('FONTSIZE', (0, 0), (-1, -1), 9),
            ('TEXTCOLOR', (0, 0), (0, -1), HexColor('#666666')),
            ('TEXTCOLOR', (2, 0), (2, -1), HexColor('#666666')),
            ('BOTTOMPADDING', (0, 0), (-1, -1), 4),
            ('TOPPADDING', (0, 0), (-1, -1), 4),
            ('GRID', (0, 0), (-1, -1), 0.5, HexColor('#e0e0e0')),
            ('BACKGROUND', (0, 0), (-1, -1), HexColor('#f8f9fa')),
        ]))
        story.append(t)
        story.append(Spacer(1, 12))

        # ── Per-Agent Sections ───────────────────────────────────────────
        agent_map = {a.agent_hostname: a for a in agents}

        for hostname in sorted(changes_by_host.keys()):
            host_changes = changes_by_host[hostname]
            ag = agent_map.get(hostname)

            status = ag.status if ag else "pending"
            rt_num = (ag.manual_rt or ag.correlated_rt) if ag else None
            cmr_num = ag.correlated_cmr if ag else None
            note = ag.correlation_note if ag else None

            rt_disp = f"RT#{rt_num}" if rt_num else "N/A"
            cmr_disp = f"CMR#{cmr_num}" if cmr_num else "N/A"

            # Host header
            story.append(Paragraph(
                f"HOST: {hostname}", styles['HostHeader']))
            story.append(HRFlowable(
                width="100%", thickness=0.5, color=HexColor('#cccccc'),
                spaceBefore=0, spaceAfter=4))

            # Agent details
            story.append(Paragraph(
                f"Review Status: <b>{status}</b> &nbsp;|&nbsp; "
                f"Changes: <b>{len(host_changes)}</b> &nbsp;|&nbsp; "
                f"RT: <b>{rt_disp}</b> &nbsp;|&nbsp; "
                f"CMR: <b>{cmr_disp}</b>",
                styles['HostDetail']))
            if note:
                story.append(Paragraph(f"Note: {note}", styles['HostDetail']))
            story.append(Spacer(1, 4))

            # Changes table
            if host_changes:
                table_data = [["Type", "Severity", "File Path", "Details"]]

                for c in host_changes:
                    ctype = (c.change_type or "unknown").upper()
                    severity = (c.severity or "medium").upper()
                    fpath = c.file_path or "unknown"

                    # Build details
                    details = []
                    bh = c.baseline_hash or ""
                    ch_hash = c.current_hash or ""
                    if bh and ch_hash and bh != ch_hash:
                        details.append(f"Hash: {bh[:12]}.. -> {ch_hash[:12]}..")
                    elif ch_hash and not bh:
                        details.append(f"Hash: N/A -> {ch_hash[:12]}..")

                    bs = c.baseline_size
                    cs = c.current_size
                    if cs is not None and bs is not None and bs != cs:
                        details.append(f"Size: {bs} -> {cs}B")
                    elif cs is not None and bs is None:
                        details.append(f"Size: N/A -> {cs}B")

                    cm = c.current_mtime
                    bm = c.baseline_mtime
                    if cm and not bm:
                        details.append(f"Mtime: N/A -> {cm.strftime('%Y-%m-%dT%H:%M:%S')}")
                    elif cm and bm and cm != bm:
                        details.append(f"Mtime: {bm.strftime('%m/%dT%H:%M')} -> {cm.strftime('%m/%dT%H:%M')}")

                    if c.analyst_notes:
                        details.append(f"Note: {c.analyst_notes[:40]}")

                    flags = []
                    if c.is_known_change:
                        flags.append("KNOWN")
                    if c.requires_investigation:
                        flags.append("INVESTIGATE")
                    if c.external_ticket_id:
                        flags.append(f"RT#{c.external_ticket_id}")
                    if flags:
                        details.append(f"[{', '.join(flags)}]")

                    detail_text = "\n".join(details) if details else ""
                    table_data.append([ctype, severity, fpath, detail_text])

                col_widths = [0.7 * inch, 0.7 * inch, 3.0 * inch, 2.4 * inch]
                ct = Table(table_data, colWidths=col_widths, repeatRows=1)
                ct.setStyle(TableStyle([
                    ('BACKGROUND', (0, 0), (-1, 0), HexColor('#1e3a5f')),
                    ('TEXTCOLOR', (0, 0), (-1, 0), white),
                    ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
                    ('FONTSIZE', (0, 0), (-1, -1), 7.5),
                    ('FONTNAME', (0, 1), (-1, -1), 'Courier'),
                    ('GRID', (0, 0), (-1, -1), 0.5, HexColor('#dddddd')),
                    ('BACKGROUND', (0, 1), (-1, -1), HexColor('#fafafa')),
                    ('VALIGN', (0, 0), (-1, -1), 'TOP'),
                    ('TOPPADDING', (0, 0), (-1, -1), 3),
                    ('BOTTOMPADDING', (0, 0), (-1, -1), 3),
                    ('LEFTPADDING', (0, 0), (-1, -1), 4),
                ]))
                story.append(ct)

            story.append(Spacer(1, 8))

        # ── Analyst Notes ────────────────────────────────────────────────
        if report.analyst_notes:
            story.append(HRFlowable(
                width="100%", thickness=0.5, color=HexColor('#cccccc'),
                spaceBefore=8, spaceAfter=4))
            story.append(Paragraph("ANALYST NOTES", styles['SectionLine']))
            safe_notes = (report.analyst_notes
                          .replace("&", "&amp;")
                          .replace("<", "&lt;")
                          .replace(">", "&gt;"))
            story.append(Paragraph(safe_notes, styles['NotesStyle']))

        # ── Footer ───────────────────────────────────────────────────────
        story.append(Spacer(1, 20))
        story.append(HRFlowable(
            width="100%", thickness=1, color=HexColor('#1e3a5f'),
            spaceBefore=4, spaceAfter=4))
        story.append(Paragraph(
            f"Generated by FIM Enterprise — {datetime.utcnow().strftime('%Y-%m-%d %H:%M UTC')}",
            styles['Footer']))

        doc.build(story)
        return buf.getvalue()
