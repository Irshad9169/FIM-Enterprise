#!/bin/bash

echo "🔍 Phase 2 Verification"
echo "======================="
echo ""

# Get token
TOKEN=$(curl -s -X POST http://localhost:8000/api/v1/auth/login \
  -H "Content-Type: application/json" \
  -d '{"username":"admin","password":"admin123"}' | python3 -c "import sys,json; print(json.load(sys.stdin)['access_token'])" 2>/dev/null)

if [ -z "$TOKEN" ]; then
    echo "❌ Failed to get auth token"
    exit 1
fi

echo "✅ Authentication successful"
echo ""

# Test endpoints
echo "1️⃣  Testing agents-enhanced search..."
RESPONSE=$(curl -s -w "\n%{http_code}" "http://localhost:8000/api/v1/agents-enhanced/search?query=test" \
  -H "Authorization: Bearer $TOKEN")
STATUS=$(echo "$RESPONSE" | tail -1)

if [ "$STATUS" = "200" ]; then
    echo "   ✅ Agents search endpoint working (HTTP $STATUS)"
else
    echo "   ❌ Agents search failed (HTTP $STATUS)"
fi

echo ""
echo "2️⃣  Testing recently scanned..."
RESPONSE=$(curl -s -w "\n%{http_code}" "http://localhost:8000/api/v1/agents-enhanced/recently-scanned?limit=5" \
  -H "Authorization: Bearer $TOKEN")
STATUS=$(echo "$RESPONSE" | tail -1)

if [ "$STATUS" = "200" ]; then
    echo "   ✅ Recently scanned endpoint working (HTTP $STATUS)"
else
    echo "   ❌ Recently scanned failed (HTTP $STATUS)"
fi

echo ""
echo "3️⃣  Testing scan trigger availability..."
AGENT_ID=$(psql -h localhost -U fim_app -d fim_db -tAc "SELECT id FROM fim.agents LIMIT 1;" 2>/dev/null)

if [ -n "$AGENT_ID" ]; then
    RESPONSE=$(curl -s -w "\n%{http_code}" -X POST "http://localhost:8000/api/v1/scan-requests/trigger/$AGENT_ID" \
      -H "Authorization: Bearer $TOKEN")
    STATUS=$(echo "$RESPONSE" | tail -1)
    
    if [ "$STATUS" = "200" ] || [ "$STATUS" = "400" ]; then
        echo "   ✅ Scan trigger endpoint accessible (HTTP $STATUS)"
    else
        echo "   ❌ Scan trigger failed (HTTP $STATUS)"
    fi
else
    echo "   ⚠️  No agents found (create agents to test)"
fi

echo ""
echo "======================="
echo "Phase 2 Verification Complete"
