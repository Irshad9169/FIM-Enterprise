#!/usr/bin/env python3
"""
Patch ReportDetailPage.tsx:
  - After publish success, Close button navigates to /reports instead of just closing modal
"""

PAGE_PATH = "/opt/fim/frontend/src/pages/ReportDetailPage.tsx"

with open(PAGE_PATH) as f:
    code = f.read()

# The PublishModal receives onClose but we need it to also navigate.
# Change the Close button after success to navigate to /reports

old_close = '''            <button onClick={onClose} className="px-6 py-2 bg-slate-700 text-white rounded text-sm hover:bg-slate-600">Close</button>'''

new_close = '''            <button onClick={() => { onClose(); window.location.href = "/reports"; }} className="px-6 py-2 bg-slate-700 text-white rounded text-sm hover:bg-slate-600">Close</button>'''

if old_close in code:
    code = code.replace(old_close, new_close)
    with open(PAGE_PATH, 'w') as f:
        f.write(code)
    print("PATCHED — PublishModal Close button now navigates to /reports")
else:
    print("WARNING: Could not find Close button pattern")
    # Try to find it
    import re
    matches = re.findall(r'Close</button>', code)
    print(f"  Found {len(matches)} 'Close</button>' occurrences")
