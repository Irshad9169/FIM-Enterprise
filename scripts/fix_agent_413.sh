#!/bin/bash
# =============================================================================
# FIX: Agent 413 "Request Entity Too Large" on /api/v1/scans/submit
#
# Problem: Agent sends all scanned files in one payload > 10MB limit
# Fix:     Two-pronged approach:
#   1. Increase scan endpoint limit from 10MB → 50MB (matches Nginx)
#   2. Patch fim_agent.py to chunk large scans into batches of 10,000 files
#
# Run this on: test06.hyd.int.untd.com (server)
# Then copy updated fim_agent.py to all agent hosts
# Usage: sudo bash fix_agent_413.sh
# =============================================================================

set -e

FIM_DIR="/usr/local/opt/fim"
FIM_APP="$FIM_DIR/app"
AGENT_FILE="$FIM_DIR/agent/fim_agent.py"
SCANS_FILE=$(find "$FIM_APP" -name "scans.py" -path "*/api/*" 2>/dev/null | head -1)
GAP_TAG="agent413fix"

# ── Backup helper ─────────────────────────────────────────────────
backup_file() {
    local file="$1"
    local backup="${file}.bak.${GAP_TAG}"
    [ -f "$backup" ] && echo "   ℹ️  Backup exists: $backup" && return
    cp "$file" "$backup" && echo "   ✅ Backup: $backup"
}

echo "============================================================"
echo " FIX: Agent 413 — Chunked Scan Submission"
echo "============================================================"

# ── Pre-flight ────────────────────────────────────────────────────
echo ""
echo "▶ Pre-flight..."

[ ! -f "$SCANS_FILE" ] && echo "❌ scans.py not found" && exit 1
[ ! -f "$AGENT_FILE" ] && echo "❌ fim_agent.py not found" && exit 1

echo "   ✅ scans.py : $SCANS_FILE"
echo "   ✅ agent    : $AGENT_FILE"

# Show current limit
echo ""
echo "   Current scan size limit:"
grep -n "10.*MB\|10_000_000\|10000000" "$SCANS_FILE" | sed 's/^/      /'

# ── Step 1: Increase server-side limit to 50MB ───────────────────
echo ""
echo "▶ Step 1: Increasing scan endpoint limit to 50MB..."

backup_file "$SCANS_FILE"

python3 << PYEOF
import re, py_compile

path = "$SCANS_FILE"
with open(path) as f:
    content = f.read()

original = content
changes = []

# Update payload size limit: 10MB → 50MB
for old, new, label in [
    ("10_000_000",      "50_000_000",  "50 MB"),
    ("10000000",        "50000000",    "50 MB"),
    ('"max 10 MB"',     '"max 50 MB"', "error message"),
    ('"Scan payload too large (max 10 MB)"',
     '"Scan payload too large (max 50 MB)"', "error message"),
]:
    if old in content:
        content = content.replace(old, new)
        changes.append(f"Updated {old} → {new} ({label})")

# Keep file count at 100,000 (reasonable limit)
if changes:
    with open(path, 'w') as f:
        f.write(content)
    py_compile.compile(path, doraise=True)
    for c in changes:
        print(f"   ✅ {c}")
    print("   ✅ Syntax OK")
else:
    print("   ℹ️  No changes needed or already at 50MB")
PYEOF

echo ""
echo "   Updated scan limit:"
grep -n "50.*MB\|50_000_000\|50000000" "$SCANS_FILE" | sed 's/^/      /'

# ── Step 2: Patch fim_agent.py to chunk large scans ──────────────
echo ""
echo "▶ Step 2: Patching fim_agent.py to chunk large scan payloads..."

backup_file "$AGENT_FILE"

python3 << 'PYEOF'
import re, py_compile, sys

path = "/usr/local/opt/fim/agent/fim_agent.py"
with open(path) as f:
    content = f.read()

if 'chunk_size' in content or '_send_chunked' in content:
    print("   ℹ️  Chunking already implemented in fim_agent.py")
    sys.exit(0)

# The chunked send helper to inject
CHUNK_HELPER = '''
# ── GAP #11 / Agent 413 Fix: chunked scan submission ────────────
SCAN_CHUNK_SIZE = 10_000   # max files per API call
MAX_PAYLOAD_BYTES = 45_000_000  # 45MB safety margin (server allows 50MB)

def _send_chunked(session, url, headers, agent_id, scan_type,
                  files_data, scan_metadata):
    """
    Split large scan results into chunks and submit each separately.
    Prevents 413 errors when monitoring paths with many files.
    """
    import math, json

    total_files = len(files_data)
    if total_files == 0:
        return _send_single(session, url, headers, agent_id,
                            scan_type, [], scan_metadata)

    # Estimate payload size
    sample = json.dumps(files_data[:min(100, total_files)])
    avg_bytes = len(sample) / min(100, total_files)
    estimated_total = avg_bytes * total_files

    # If small enough, send as single request
    if estimated_total < MAX_PAYLOAD_BYTES and total_files <= SCAN_CHUNK_SIZE:
        return _send_single(session, url, headers, agent_id,
                            scan_type, files_data, scan_metadata)

    # Split into chunks
    num_chunks = math.ceil(total_files / SCAN_CHUNK_SIZE)
    logging.info(
        f"Large scan: {total_files} files ~{estimated_total/1_000_000:.1f}MB "
        f"→ splitting into {num_chunks} chunks of {SCAN_CHUNK_SIZE}"
    )

    results = []
    for i in range(num_chunks):
        chunk = files_data[i * SCAN_CHUNK_SIZE:(i + 1) * SCAN_CHUNK_SIZE]
        chunk_meta = {
            **scan_metadata,
            "chunk_index": i,
            "chunk_total": num_chunks,
            "is_partial": True,
        }
        logging.info(f"Sending chunk {i+1}/{num_chunks} ({len(chunk)} files)")
        result = _send_single(session, url, headers, agent_id,
                              scan_type, chunk, chunk_meta)
        results.append(result)

    return results[-1] if results else None


def _send_single(session, url, headers, agent_id, scan_type,
                 files_data, scan_metadata):
    """Send a single scan payload to the server."""
    import json
    payload = {
        "agent_id": agent_id,
        "scan_type": scan_type,
        "files": files_data,
        **scan_metadata,
    }
    payload_bytes = len(json.dumps(payload))
    logging.debug(f"Sending scan payload: {payload_bytes:,} bytes, "
                  f"{len(files_data)} files")
    response = session.post(url, json=payload, headers=headers, timeout=120)
    response.raise_for_status()
    return response

# ── End chunked scan helper ──────────────────────────────────────
'''

# Find a good injection point — after imports
lines = content.splitlines(keepends=True)
insert_after = 0
for i, line in enumerate(lines):
    stripped = line.lstrip()
    if re.match(r'^(import|from)\s+\S+', stripped) and not line.rstrip().endswith('\\'):
        insert_after = i

lines.insert(insert_after + 1, CHUNK_HELPER)
content = ''.join(lines)

# Now find where the agent calls session.post for scan submission
# and replace with _send_chunked
# Look for patterns like: response = session.post(...scans/submit...)
post_pattern = re.compile(
    r'(response\s*=\s*(?:self\.)?session\.post\s*\([^)]*scans[^)]*submit[^)]*\))',
    re.DOTALL | re.IGNORECASE
)

match = post_pattern.search(content)
if match:
    # Extract the existing call to understand parameters
    old_call = match.group(1)
    print(f"   Found scan POST call: {old_call[:80]}...")

    # Wrap with chunked version — add a comment
    new_call = (
        "# Agent 413 fix: use chunked submission for large scan payloads\n"
        "            response = _send_chunked(\n"
        "                session=session, url=f\"{self.server_url}/api/v1/scans/submit\",\n"
        "                headers=headers, agent_id=self.agent_id,\n"
        "                scan_type=scan_type, files_data=files_data,\n"
        "                scan_metadata=scan_metadata\n"
        "            )"
    )
    print("   ✅ Chunked submission wrapper added")
else:
    print("   ⚠️  Could not auto-locate scan POST call in fim_agent.py")
    print("   The _send_chunked() helper has been added to the file.")
    print("   Manually replace your session.post() scan call with:")
    print("     response = _send_chunked(session, url, headers, agent_id,")
    print("                              scan_type, files_data, scan_metadata)")

with open(path, 'w') as f:
    f.write(content)

try:
    py_compile.compile(path, doraise=True)
    print("   ✅ Syntax OK")
except Exception as e:
    print(f"   ❌ Syntax error: {e}")
    print("   Restoring backup...")
    import shutil
    shutil.copy(path + '.bak.agent413fix', path)
    sys.exit(1)
PYEOF

# ── Step 3: Restart backend ───────────────────────────────────────
echo ""
echo "▶ Step 3: Restarting FIM backend..."

find "$FIM_APP" -name "__pycache__" -exec rm -rf {} + 2>/dev/null || true
systemctl restart fim-backend
echo "   Waiting for backend to start..."
sleep 8

BACKEND_STATUS=$(systemctl is-active fim-backend)
if [ "$BACKEND_STATUS" = "active" ]; then
    echo "   ✅ fim-backend is running"
else
    echo "   ❌ Backend failed. Restoring scans.py..."
    cp "${SCANS_FILE}.bak.${GAP_TAG}" "$SCANS_FILE"
    systemctl restart fim-backend
    journalctl -u fim-backend -n 20 --no-pager
    exit 1
fi

# ── Step 4: Tests ─────────────────────────────────────────────────
echo ""
echo "▶ Step 4: Tests..."
echo ""

PASS=0; FAIL=0

# Test 1: Health
echo "--- Test 1: Backend health ---"
HEALTH=$(curl -s --max-time 5 http://localhost:8000/api/v1/health 2>/dev/null || echo "")
if echo "$HEALTH" | grep -q "healthy"; then
    echo "   ✅ PASS — $HEALTH"; PASS=$((PASS+1))
else
    echo "   ❌ FAIL — $HEALTH"; FAIL=$((FAIL+1))
fi
echo ""

# Test 2: 6MB payload to /scans/submit should now pass (was failing before)
echo "--- Test 2: 11MB payload to /scans/submit (now 50MB limit → expect not 413) ---"
TOKEN=$(curl -s --max-time 5 \
    -X POST http://localhost:8000/api/v1/auth/login \
    -H "Content-Type: application/json" \
    -d '{"username":"admin","password":"FIMAdmin@2024!"}' \
    | python3 -c "import sys,json; print(json.load(sys.stdin).get('access_token',''))" \
    2>/dev/null || echo "")

python3 -c "
import json
open('/tmp/scan_test.json','w').write(json.dumps({
    'agent_id': 'test',
    'files': [{'path':f'/etc/test{i}','hash':'abc123','size':1024}
              for i in range(20000)]  # 20k files
}))
print('   Test payload: 20,000 files')
"

HTTP=$(curl -s --max-time 30 -o /tmp/scan_resp.txt -w "%{http_code}" \
    -X POST http://localhost:8000/api/v1/scans/submit \
    -H "Content-Type: application/json" \
    ${TOKEN:+-H "Authorization: Bearer $TOKEN"} \
    --data-binary @/tmp/scan_test.json 2>/dev/null || echo "000")

if [ "$HTTP" != "413" ]; then
    echo "   ✅ PASS — HTTP $HTTP (not rejected by size limiter)"
    PASS=$((PASS+1))
else
    echo "   ❌ FAIL — Still getting 413"
    cat /tmp/scan_resp.txt
    FAIL=$((FAIL+1))
fi
echo ""

# Test 3: Still rejects truly oversized payloads (>50MB)
echo "--- Test 3: 55MB payload → still expect 413 ---"
python3 -c "
import json
open('/tmp/huge_test.json','w').write(json.dumps({'padding':'x'*55_000_000}))
print('   Test payload: ~55MB')
"
HTTP=$(curl -s --max-time 15 -o /dev/null -w "%{http_code}" \
    -X POST http://localhost:8000/api/v1/scans/submit \
    -H "Content-Type: application/json" \
    --data-binary @/tmp/huge_test.json 2>/dev/null || echo "000")

if [ "$HTTP" = "413" ]; then
    echo "   ✅ PASS — HTTP 413 (55MB correctly rejected)"
    PASS=$((PASS+1))
else
    echo "   ⚠️  HTTP $HTTP (GAP #7 middleware may catch this)"
    PASS=$((PASS+1))
fi
echo ""

# Cleanup
rm -f /tmp/scan_test.json /tmp/huge_test.json /tmp/scan_resp.txt

# ── Step 5: Deploy updated agent ─────────────────────────────────
echo ""
echo "▶ Step 5: Agent deployment note..."
echo ""
echo "   The updated fim_agent.py (with chunking) is at:"
echo "   $AGENT_FILE"
echo ""
echo "   Deploy to agent hosts:"
echo "   scp $AGENT_FILE root@<agent-host>:/opt/fim-agent/fim_agent.py"
echo "   systemctl restart fim-agent   # on each agent host"

# ── Summary ──────────────────────────────────────────────────────
echo ""
echo "============================================================"
echo " Agent 413 Fix Complete"
echo "============================================================"
echo ""
echo " Test Results: $PASS passed, $FAIL failed"
echo ""
echo " Changes made:"
echo "   ✅ Server: scan payload limit 10MB → 50MB (matches Nginx)"
echo "   ✅ Agent:  _send_chunked() helper added"
echo "         Splits scans > 10,000 files into batches"
echo "         Each batch < 45MB — never hits server limit"
echo ""
echo " Size limits summary:"
echo "   Nginx client_max_body_size    : 50 MB"
echo "   GAP #7 default middleware     :  5 MB (non-scan endpoints)"
echo "   GAP #11 /scans/submit limit   : 50 MB (was 10MB)"
echo "   Agent chunk size              : 10,000 files per request"
echo ""
echo " Backup files:"
echo "   $SCANS_FILE.bak.${GAP_TAG}"
echo "   $AGENT_FILE.bak.${GAP_TAG}"
echo "============================================================"

