#!/usr/bin/env python3
"""
Patch ReportDetailPage.tsx to:
1. Add exportPdfReport function to API calls
2. Add PDF download handler
3. Replace Print button with PDF download button
4. Rename Export to "Export Text"
Run: python3 /opt/fim/patch_frontend_export.py
"""

# ── 1. Patch dashboard.ts API client ─────────────────────────────────────
API_PATH = "/opt/fim/frontend/src/api/dashboard.ts"

with open(API_PATH) as f:
    api_code = f.read()

# Add exportPdfReport function after exportReport
if 'exportPdfReport' not in api_code:
    old_export = '''export const exportReport = async (reportId: string): Promise<Blob> => {
  const token = localStorage.getItem("fim_token");
  const response = await fetch(`/api/v1/reports/${reportId}/export`, {
    headers: { Authorization: `Bearer ${token}` },
  });
  if (!response.ok) throw new Error("Failed to export report");
  return response.blob();
};'''

    new_export = '''export const exportReport = async (reportId: string): Promise<Blob> => {
  const token = localStorage.getItem("fim_token");
  const response = await fetch(`/api/v1/reports/${reportId}/export`, {
    headers: { Authorization: `Bearer ${token}` },
  });
  if (!response.ok) throw new Error("Failed to export report");
  return response.blob();
};

export const exportPdfReport = async (reportId: string): Promise<Blob> => {
  const token = localStorage.getItem("fim_token");
  const response = await fetch(`/api/v1/reports/${reportId}/export/pdf`, {
    headers: { Authorization: `Bearer ${token}` },
  });
  if (!response.ok) throw new Error("Failed to export PDF report");
  return response.blob();
};'''

    if old_export in api_code:
        api_code = api_code.replace(old_export, new_export)
        with open(API_PATH, 'w') as f:
            f.write(api_code)
        print(f"PATCHED {API_PATH} — added exportPdfReport")
    else:
        print(f"WARNING: Could not find exportReport in {API_PATH} — manually add exportPdfReport")
else:
    print(f"SKIPPED {API_PATH} — exportPdfReport already exists")


# ── 2. Patch ReportDetailPage.tsx ─────────────────────────────────────────
PAGE_PATH = "/opt/fim/frontend/src/pages/ReportDetailPage.tsx"

with open(PAGE_PATH) as f:
    page_code = f.read()

# 2a. Add exportPdfReport to the import line
if 'exportPdfReport' not in page_code:
    # Find the import line that has exportReport
    page_code = page_code.replace(
        'exportReport,',
        'exportReport, exportPdfReport,'
    )
    # Also try without trailing comma
    if 'exportPdfReport' not in page_code:
        page_code = page_code.replace(
            'exportReport,',
            'exportReport, exportPdfReport,'
        )
    print("  Added exportPdfReport to imports")

# 2b. Add exportingPdf state
if 'exportingPdf' not in page_code:
    page_code = page_code.replace(
        'const [exporting,    setExporting]    = useState(false);',
        'const [exporting,    setExporting]    = useState(false);\n'
        '  const [exportingPdf, setExportingPdf] = useState(false);'
    )
    print("  Added exportingPdf state")

# 2c. Add handleExportPdf function after handleExport
if 'handleExportPdf' not in page_code:
    old_handle = '''  const handleExport = async () => {
    if (!reportId) return;
    setExporting(true);
    try {
      const blob = await exportReport(reportId);
      const url  = URL.createObjectURL(blob);
      const a    = document.createElement("a");
      a.href     = url;
      a.download = `FIM-report-${report?.report_date || reportId}.txt`;
      a.click();
      URL.revokeObjectURL(url);
    } finally { setExporting(false); }
  };'''

    new_handle = '''  const handleExport = async () => {
    if (!reportId) return;
    setExporting(true);
    try {
      const blob = await exportReport(reportId);
      const url  = URL.createObjectURL(blob);
      const a    = document.createElement("a");
      a.href     = url;
      a.download = `FIM-report-${report?.report_date || reportId}.txt`;
      a.click();
      URL.revokeObjectURL(url);
    } finally { setExporting(false); }
  };

  const handleExportPdf = async () => {
    if (!reportId) return;
    setExportingPdf(true);
    try {
      const blob = await exportPdfReport(reportId);
      const url  = URL.createObjectURL(blob);
      const a    = document.createElement("a");
      a.href     = url;
      a.download = `FIM-report-${report?.report_date || reportId}.pdf`;
      a.click();
      URL.revokeObjectURL(url);
    } finally { setExportingPdf(false); }
  };'''

    if old_handle in page_code:
        page_code = page_code.replace(old_handle, new_handle)
        print("  Added handleExportPdf function")
    else:
        print("  WARNING: Could not find handleExport function — manually add handleExportPdf")

# 2d. Replace Print button with PDF button, rename Export to "Text"
# Old Export button
page_code = page_code.replace(
    '<Download size={13} /> {exporting ? "…" : "Export"}',
    '<Download size={13} /> {exporting ? "…" : "Export TXT"}'
)

# Old Print button -> PDF download
old_print = '''            <button onClick={() => window.print()} className="px-3 py-2 bg-slate-800 text-slate-200 border border-slate-700 text-xs rounded flex items-center gap-1.5 hover:bg-slate-700">
              <Printer size={13} /> Print
            </button>'''

new_pdf = '''            <button onClick={handleExportPdf} disabled={exportingPdf} className="px-3 py-2 bg-slate-800 text-slate-200 border border-slate-700 text-xs rounded flex items-center gap-1.5 hover:bg-slate-700">
              <Download size={13} /> {exportingPdf ? "…" : "Export PDF"}
            </button>'''

if old_print in page_code:
    page_code = page_code.replace(old_print, new_pdf)
    print("  Replaced Print button with Export PDF button")
else:
    print("  WARNING: Could not find Print button — manually replace")

# 2e. Remove Printer from imports if present, ensure Download is imported
# Printer may still be in imports but unused — leave it, no harm
# Just make sure the page compiles

with open(PAGE_PATH, 'w') as f:
    f.write(page_code)

print(f"PATCHED {PAGE_PATH}")
print("\nDone! Now run:")
print("  cd /opt/fim/frontend && npm run build")
print("  systemctl restart fim-backend")
