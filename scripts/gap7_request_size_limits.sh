#!/bin/bash
# =============================================================================
# GAP #7 FIX: Request Size Limits
# Run this on: test06.hyd.int.untd.com
# Usage: sudo bash gap7_request_size_limits.sh
# =============================================================================

set -e  # Exit on any error

FIM_APP="/usr/local/opt/fim/app"
MIDDLEWARE_DIR="$FIM_APP/middleware"
MAIN_PY="$FIM_APP/main.py"

echo "============================================================"
echo " GAP #7: Adding Request Size Limit Middleware"
echo "============================================================"

# ── Pre-flight checks ────────────────────────────────────────────
echo ""
echo "▶ Pre-flight checks..."

if [ ! -d "$FIM_APP" ]; then
    echo "❌ FIM app directory not found: $FIM_APP"
    echo "   Update FIM_APP variable at top of this script and re-run."
    exit 1
fi

if [ ! -f "$MAIN_PY" ]; then
    echo "❌ main.py not found at: $MAIN_PY"
    exit 1
fi

if [ ! -d "$MIDDLEWARE_DIR" ]; then
    mkdir -p "$MIDDLEWARE_DIR"
    echo "   Created middleware directory"
fi

echo "✅ All paths confirmed"

# ── Step 1: Create middleware file ───────────────────────────────
echo ""
echo "▶ Step 1: Creating request_size_limiter.py..."

cat > "$MIDDLEWARE_DIR/request_size_limiter.py" << 'PYEOF'
"""
Request Size Limit Middleware
Prevents DoS attacks via oversized payloads (GAP #7 fix).
"""

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import JSONResponse
from fastapi import Request
import logging

logger = logging.getLogger(__name__)

# Per-endpoint size limits (bytes)
ENDPOINT_SIZE_LIMITS = {
    '/api/v1/scans/submit':  50_000_000,   # 50 MB — scan payloads can be large
    '/api/v1/reports/':      10_000_000,   # 10 MB
    '/api/v1/baselines/':    20_000_000,   # 20 MB
    'default':                5_000_000,   #  5 MB — everything else
}


class RequestSizeLimitMiddleware(BaseHTTPMiddleware):
    """
    Enforce request body size limits per endpoint.
    Rejects oversized requests with HTTP 413 before the body is read.
    """

    async def dispatch(self, request: Request, call_next):
        content_length = request.headers.get('content-length')

        if content_length:
            try:
                content_length = int(content_length)
            except ValueError:
                return JSONResponse(
                    status_code=400,
                    content={"detail": "Invalid Content-Length header"}
                )

            # Resolve limit for this path
            path = request.url.path
            limit = ENDPOINT_SIZE_LIMITS['default']
            for pattern, endpoint_limit in ENDPOINT_SIZE_LIMITS.items():
                if pattern != 'default' and path.startswith(pattern):
                    limit = endpoint_limit
                    break

            if content_length > limit:
                logger.warning(
                    "Request size limit exceeded: %d bytes (limit: %d) "
                    "from %s to %s",
                    content_length, limit,
                    request.client.host if request.client else "unknown",
                    path,
                )
                return JSONResponse(
                    status_code=413,
                    content={
                        "detail": (
                            f"Request body too large. "
                            f"Maximum allowed for this endpoint: "
                            f"{limit / 1_000_000:.0f} MB"
                        )
                    },
                )

        return await call_next(request)
PYEOF

echo "✅ Middleware file created: $MIDDLEWARE_DIR/request_size_limiter.py"

# ── Step 2: Patch main.py ────────────────────────────────────────
echo ""
echo "▶ Step 2: Patching main.py..."

# Backup first
cp "$MAIN_PY" "$MAIN_PY.bak.gap7"
echo "   Backup saved: $MAIN_PY.bak.gap7"

python3 << PYEOF
import re, sys

path = "$MAIN_PY"
with open(path) as f:
    code = f.read()

changed = False

# 1. Add import (idempotent)
import_line = "from app.middleware.request_size_limiter import RequestSizeLimitMiddleware"
if import_line not in code:
    # Inject after the rate limiter import if present, else after first 'from app' line
    if "from app.middleware.rate_limiter import RateLimiterMiddleware" in code:
        code = code.replace(
            "from app.middleware.rate_limiter import RateLimiterMiddleware",
            "from app.middleware.rate_limiter import RateLimiterMiddleware\n"
            + import_line,
        )
    else:
        # Fallback: add after the last 'from app' import block
        code = re.sub(
            r"(from app\.[^\n]+\n)(?!from app)",
            r"\1" + import_line + "\n",
            code,
            count=1,
        )
    changed = True
    print("   ✅ Import added")
else:
    print("   ℹ️  Import already present — skipping")

# 2. Register middleware (idempotent)
register_line = "app.add_middleware(RequestSizeLimitMiddleware)"
if register_line not in code:
    # Prefer inserting after RateLimiterMiddleware registration
    if "app.add_middleware(RateLimiterMiddleware)" in code:
        code = code.replace(
            "app.add_middleware(RateLimiterMiddleware)",
            "app.add_middleware(RateLimiterMiddleware)\n"
            + register_line,
        )
    else:
        # Fallback: after CORSMiddleware block
        code = re.sub(
            r"(app\.add_middleware\(CORSMiddleware.*?\))",
            r"\1\n" + register_line,
            code,
            count=1,
            flags=re.DOTALL,
        )
    changed = True
    print("   ✅ Middleware registered")
else:
    print("   ℹ️  Middleware already registered — skipping")

if changed:
    with open(path, "w") as f:
        f.write(code)
    print("   ✅ main.py updated")
else:
    print("   ℹ️  main.py unchanged")
PYEOF

# Verify patch
echo ""
echo "   Verifying patch..."
if grep -q "RequestSizeLimitMiddleware" "$MAIN_PY"; then
    echo "   ✅ Confirmed in main.py:"
    grep -n "RequestSizeLimitMiddleware" "$MAIN_PY"
else
    echo "   ❌ Patch failed — check main.py manually"
    exit 1
fi

# ── Step 3: Nginx client_max_body_size ──────────────────────────
echo ""
echo "▶ Step 3: Checking Nginx config..."

NGINX_CONF="/etc/nginx/conf.d/fim.conf"
if [ -f "$NGINX_CONF" ]; then
    if grep -q "client_max_body_size" "$NGINX_CONF"; then
        echo "   ✅ client_max_body_size already set:"
        grep "client_max_body_size" "$NGINX_CONF"
    else
        # Add inside the server block, before the first location block
        sed -i '/^\s*server\s*{/a\    client_max_body_size 50M;' "$NGINX_CONF"
        echo "   ✅ Added client_max_body_size 50M to Nginx config"
    fi

    # Test and reload Nginx
    if nginx -t 2>&1; then
        systemctl reload nginx
        echo "   ✅ Nginx reloaded"
    else
        echo "   ❌ Nginx config test failed — reload skipped"
    fi
else
    echo "   ⚠️  $NGINX_CONF not found — skipping Nginx step"
fi

# ── Step 4: Restart backend ──────────────────────────────────────
echo ""
echo "▶ Step 4: Restarting FIM backend..."

find "$FIM_APP" -name "__pycache__" -exec rm -rf {} + 2>/dev/null || true

systemctl restart fim-backend
sleep 3

STATUS=$(systemctl is-active fim-backend)
if [ "$STATUS" = "active" ]; then
    echo "   ✅ fim-backend is running"
else
    echo "   ❌ fim-backend failed to start — check logs:"
    journalctl -u fim-backend -n 20 --no-pager
    exit 1
fi

# ── Step 5: Functional tests ─────────────────────────────────────
echo ""
echo "▶ Step 5: Running tests..."
echo ""

# Health check
echo "--- Test 0: Health check ---"
curl -s http://localhost:8000/api/v1/health | python3 -m json.tool 2>/dev/null || \
    curl -s http://localhost:8000/api/v1/health
echo ""

# Login (small payload — must succeed)
echo "--- Test 1: Small login request (should succeed with 200) ---"
HTTP_CODE=$(curl -s -o /dev/null -w "%{http_code}" \
    -X POST http://localhost:8000/api/v1/auth/login \
    -H "Content-Type: application/json" \
    -d '{"username":"admin","password":"FIMAdmin@2024!"}')
if [ "$HTTP_CODE" = "200" ]; then
    echo "✅ PASS — HTTP $HTTP_CODE (login accepted)"
else
    echo "⚠️  HTTP $HTTP_CODE (unexpected — check credentials)"
fi
echo ""

# Oversized payload — must be rejected with 413
echo "--- Test 2: 6 MB payload to default endpoint (limit 5 MB — should get 413) ---"
python3 -c "import json; open('/tmp/big_payload.json','w').write(json.dumps({'data':'x'*6_000_000}))"
HTTP_CODE=$(curl -s -o /tmp/test2_response.txt -w "%{http_code}" \
    -X POST http://localhost:8000/api/v1/users \
    -H "Content-Type: application/json" \
    --data-binary @/tmp/big_payload.json)
if [ "$HTTP_CODE" = "413" ]; then
    echo "✅ PASS — HTTP 413 (correctly rejected)"
    cat /tmp/test2_response.txt | python3 -m json.tool 2>/dev/null
else
    echo "❌ FAIL — HTTP $HTTP_CODE (expected 413)"
    cat /tmp/test2_response.txt
fi
echo ""

# Scan endpoint — 6 MB should pass (50 MB limit)
echo "--- Test 3: 6 MB payload to /scans/submit (limit 50 MB — should NOT get 413) ---"
HTTP_CODE=$(curl -s -o /tmp/test3_response.txt -w "%{http_code}" \
    -X POST http://localhost:8000/api/v1/scans/submit \
    -H "Content-Type: application/json" \
    --data-binary @/tmp/big_payload.json)
if [ "$HTTP_CODE" != "413" ]; then
    echo "✅ PASS — HTTP $HTTP_CODE (not rejected by size limiter; endpoint handled it)"
else
    echo "❌ FAIL — HTTP 413 (scan endpoint incorrectly rejected 6 MB payload)"
fi
echo ""

# Cleanup temp files
rm -f /tmp/big_payload.json /tmp/test2_response.txt /tmp/test3_response.txt

echo "============================================================"
echo " GAP #7 Implementation Complete"
echo "============================================================"
echo ""
echo " Summary of limits applied:"
echo "   /api/v1/scans/submit  → 50 MB"
echo "   /api/v1/reports/*     → 10 MB"
echo "   /api/v1/baselines/*   → 20 MB"
echo "   All other endpoints   →  5 MB"
echo "   Nginx (outer shield)  → 50 MB"
echo ""
echo " Next: GAP #8 — Database Connection Encryption"
echo "============================================================"
