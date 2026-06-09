#!/bin/bash

echo "🔍 Phase 1 Verification"
echo "======================="
echo ""

# 1. Check database tables
echo "1️⃣  Checking database tables..."
TABLE_COUNT=$(psql -h localhost -U fim_app -d fim_db -tAc "SELECT COUNT(*) FROM information_schema.tables WHERE table_schema='fim' AND table_name IN ('reports', 'correlation_groups', 'report_changes', 'rt_ticket_cache', 'scan_requests');")

if [ "$TABLE_COUNT" = "5" ]; then
    echo "   ✅ All 5 tables created"
else
    echo "   ❌ Expected 5 tables, found $TABLE_COUNT"
fi

# 2. Check backup configuration
echo ""
echo "2️⃣  Checking backup configuration..."
if [ -f /opt/fim/fim-backups/scripts/backup_fim.sh ]; then
    echo "   ✅ Backup script exists"
else
    echo "   ❌ Backup script missing"
fi

if crontab -l 2>/dev/null | grep -q backup_fim.sh; then
    echo "   ✅ Backup cron job configured"
else
    echo "   ⚠️  Backup cron job not found"
fi

# 3. Check RBAC
echo ""
echo "3️⃣  Checking RBAC setup..."
if [ -f /opt/fim/app/core/rbac.py ]; then
    echo "   ✅ RBAC module exists"
else
    echo "   ❌ RBAC module missing"
fi

# 4. Check audit service
echo ""
echo "4️⃣  Checking audit service..."
if [ -f /opt/fim/app/services/audit_service.py ]; then
    echo "   ✅ Audit service exists"
else
    echo "   ❌ Audit service missing"
fi

# 5. Check test users
echo ""
echo "5️⃣  Checking test users..."
USER_COUNT=$(psql -h localhost -U fim_app -d fim_db -tAc "SELECT COUNT(*) FROM fim.users WHERE username IN ('admin', 'analyst1', 'trainee1', 'auditor1');")

if [ "$USER_COUNT" = "4" ]; then
    echo "   ✅ All 4 test users created"
    psql -h localhost -U fim_app -d fim_db -c "SELECT username, role FROM fim.users WHERE username IN ('admin', 'analyst1', 'trainee1', 'auditor1') ORDER BY username;"
else
    echo "   ❌ Expected 4 test users, found $USER_COUNT"
fi

# 6. Test API
echo ""
echo "6️⃣  Testing API..."

# Check if systemd service exists and is running
if systemctl list-units --type=service --all | grep -q fim-server.service; then
    SERVICE_STATUS=$(systemctl is-active fim-server 2>/dev/null || echo "inactive")
    
    if [ "$SERVICE_STATUS" = "active" ]; then
        echo "   ✅ FIM server is running (systemd)"
    else
        echo "   ⚠️  FIM server systemd status: $SERVICE_STATUS"
    fi
else
    echo "   ⚠️  FIM server systemd service not found"
fi

# Actually test if port 8000 is listening
if netstat -tln 2>/dev/null | grep -q ":8000 " || ss -tln 2>/dev/null | grep -q ":8000 "; then
    echo "   ✅ Port 8000 is listening"
    
    # Test health endpoint
    HEALTH_CHECK=$(curl -s --max-time 5 http://localhost:8000/api/v1/health 2>/dev/null)
    if echo "$HEALTH_CHECK" | grep -q "healthy"; then
        echo "   ✅ Health endpoint responding"
    else
        echo "   ⚠️  Health endpoint not responding"
    fi
    
    # Test login
    LOGIN_RESPONSE=$(curl -s --max-time 5 -X POST http://localhost:8000/api/v1/auth/login \
      -H "Content-Type: application/json" \
      -d '{"username":"admin","password":"admin123"}' 2>/dev/null)
    
    if echo "$LOGIN_RESPONSE" | grep -q "access_token"; then
        echo "   ✅ Login successful"
        
        # Extract and display role
        ROLE=$(echo "$LOGIN_RESPONSE" | python3 -c "import sys, json; print(json.load(sys.stdin)['user']['role'])" 2>/dev/null || echo "unknown")
        echo "   ✅ User role: $ROLE"
    else
        echo "   ❌ Login failed"
        echo "      Response: $LOGIN_RESPONSE"
    fi
else
    echo "   ❌ Port 8000 not listening"
    echo "      Checking process..."
    if pgrep -f "uvicorn app.main:app" > /dev/null; then
        echo "      ⚠️  Uvicorn process found but port not listening"
        echo "      Wait a few seconds and try again"
    else
        echo "      ❌ No uvicorn process found"
    fi
fi

echo ""
echo "======================="
echo "Phase 1 Verification Complete"
