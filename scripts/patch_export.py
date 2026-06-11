#!/usr/bin/env python3
"""
Patch reports.py to:
1. Replace the old text export with rich format (hashes, sizes, mtimes)
2. Add a new PDF export endpoint
Run: python3 /opt/fim/patch_export.py
"""
import re

REPORTS_PATH = "/opt/fim/app/api/reports.py"

with open(REPORTS_PATH) as f:
    code = f.read()

# ── 1. Find and replace the export_report function ────────────────────────

# Find the old export function
old_export_marker = 'async def export_report('
if old_export_marker not in code:
    print("ERROR: export_report function not found!")
    exit(1)

# Find the start of the export function (including decorator)
lines = code.split('\n')
export_start = None
export_end = None
for i, line in enumerate(lines):
    if old_export_marker in line:
        # Go back to find @router decorator
        j = i - 1
        while j >= 0 and (lines[j].strip().startswith('@') or lines[j].strip() == ''):
            j -= 1
        export_start = j + 1
    # Find the next route or section after export_report
    if export_start is not None and i > export_start + 5:
        if (line.startswith('@router.') or line.startswith('# ──')) and i > export_start + 10:
            export_end = i
            break

if not export_start or not export_end:
    print(f"ERROR: Could not find export function boundaries (start={export_start}, end={export_end})")
    exit(1)

print(f"Found export_report at lines {export_start+1}-{export_end+1}")

# Build replacement
new_export = '''
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

'''

# Replace
lines[export_start:export_end] = [new_export]
code = '\n'.join(lines)

with open(REPORTS_PATH, 'w') as f:
    f.write(code)

print("PATCHED reports.py — added rich text export + PDF export endpoints")
print(f"  GET /reports/{{id}}/export      → rich plaintext")
print(f"  GET /reports/{{id}}/export/pdf  → formatted PDF")
