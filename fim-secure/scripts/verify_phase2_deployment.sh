#!/bin/bash

echo "🔍 Phase 2 Frontend Deployment Verification"
echo "==========================================="
echo ""

# Check web directory
echo "📁 Web directory:"
if [ -d "/opt/fim/web/.next" ]; then
    echo "  ✅ Build files exist"
    du -sh /opt/fim/web/.next
else
    echo "  ❌ Build files missing"
fi

echo ""
echo "🌐 API Endpoints:"

# Check agents-enhanced endpoint
if curl -s -f http://localhost:8000/api/agents-enhanced/recently-scanned?limit=1 > /dev/null 2>&1; then
    echo "  ✅ /api/agents-enhanced/recently-scanned"
else
    echo "  ❌ /api/agents-enhanced/recently-scanned (not responding)"
fi

# Check scan-requests endpoint (might 404 if no agent exists, but should respond)
STATUS=$(curl -s -o /dev/null -w "%{http_code}" http://localhost:8000/api/scan-requests/status/test-id)
if [ "$STATUS" = "404" ] || [ "$STATUS" = "200" ]; then
    echo "  ✅ /api/scan-requests/status (endpoint exists)"
else
    echo "  ⚠️  /api/scan-requests/status (status: $STATUS)"
fi

echo ""
echo "🔧 Server Status:"
systemctl is-active fim-server && echo "  ✅ Server running" || echo "  ❌ Server not running"

echo ""
echo "📊 Access URLs:"
echo "  Dashboard: http://test06.hyd.int.untd.com:8000/agents"
echo "  API Docs:  http://test06.hyd.int.untd.com:8000/docs"
