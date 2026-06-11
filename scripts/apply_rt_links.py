#!/usr/bin/env python3
"""
apply_rt_links.py — Patch all RT# references in FIM frontend to be clickable hyperlinks.
Run: python3 /opt/fim/apply_rt_links.py
"""
import shutil

RT_BASE = "https://tickets.int.untd.com/Ticket/Display.html?id="

def patch_file(path, replacements):
    shutil.copy2(path, path + ".pre-rtlink")
    with open(path, "r") as f:
        content = f.read()
    count = 0
    for old, new in replacements:
        if old in content:
            content = content.replace(old, new)
            count += 1
            print(f"  ✓ Patched: {repr(old[:70])}...")
        else:
            print(f"  ✗ NOT FOUND: {repr(old[:70])}...")
    with open(path, "w") as f:
        f.write(content)
    print(f"  Total patches applied: {count}")

# ── ReportDetailPage.tsx ──────────────────────────────────────────────────

print("\n=== Patching ReportDetailPage.tsx ===")
patch_file("/opt/fim/frontend/src/pages/ReportDetailPage.tsx", [

    # 1. Report header RT badge (line ~731)
    (
        '<span className="text-green-300 text-xs font-mono">RT#{report.rt_ticket_id}</span>',
        '<a href={`' + RT_BASE + '${report.rt_ticket_id}`} target="_blank" rel="noopener noreferrer" className="text-green-300 text-xs font-mono hover:text-green-200 hover:underline">RT#{report.rt_ticket_id}</a>',
    ),

    # 2. Agent card RT badge (line ~398-400) — exact whitespace from source
    (
        '''<span className="text-xs bg-blue-900/40 text-blue-300 border border-blue-800/50 px-1.5 py-0.5 rounded font-mono">
                RT#{effectiveRt}
              </span>''',
        '''<a href={`''' + RT_BASE + '''${effectiveRt}`} target="_blank" rel="noopener noreferrer" className="text-xs bg-blue-900/40 text-blue-300 border border-blue-800/50 px-1.5 py-0.5 rounded font-mono hover:text-blue-200 hover:underline">
                RT#{effectiveRt}
              </a>''',
    ),

    # 3. Per-change RT badge (line ~290)
    (
        '<span className="text-green-400 text-[10px] font-bold">RT#{change.external_ticket_id}</span>',
        '<a href={`' + RT_BASE + '${change.external_ticket_id}`} target="_blank" rel="noopener noreferrer" className="text-green-400 text-[10px] font-bold hover:text-green-300 hover:underline">RT#{change.external_ticket_id}</a>',
    ),
])

# ── ReportsPage.tsx ───────────────────────────────────────────────────────

print("\n=== Patching ReportsPage.tsx ===")
patch_file("/opt/fim/frontend/src/pages/ReportsPage.tsx", [

    # Reports list RT badge (line ~165-167) — exact whitespace from source
    (
        '''<span className="text-purple-400 text-xs font-mono" title="Published to RT">
                              RT#{report.rt_ticket_id}
                            </span>''',
        '''<a href={`''' + RT_BASE + '''${report.rt_ticket_id}`} target="_blank" rel="noopener noreferrer" className="text-purple-400 text-xs font-mono hover:text-purple-300 hover:underline" title="Published to RT">
                              RT#{report.rt_ticket_id}
                            </a>''',
    ),
])

print("\n=== All patches applied ===")
print("Next: cd /opt/fim/frontend && npm run build")
