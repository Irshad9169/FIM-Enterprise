#!/bin/bash

echo "🔍 FIM Dashboard Verification"
echo "============================="
echo ""

# Check frontend build
echo "1️⃣  Checking frontend build..."
if [ -d "/opt/fim/web" ] && [ "$(ls -A /opt/fim/web)" ]; then
    echo "   ✅ Frontend build exists"
    echo "      Files: $(find /opt/fim/web -type f | wc -l)"
    echo "      Size: $(du -sh /opt/fim/web | cut -f1)"
else
    echo "   ❌ Frontend build missing"
    echo "      Run: /opt/fim/scripts/build-frontend.sh"
fi
echo ""

# Check FIM server
echo "2️⃣  Checking FIM server..."
if systemctl is-active --quiet fim-server; then
    echo "   ✅ FIM server is running"
    echo "      Status: $(systemctl is-active fim-server)"
    echo "      Port: 8000"
else
    echo "   ❌ FIM server not running"
    echo "      Start: systemctl start fim-server"
fi
echo ""

# Check HTTP response
echo "3️⃣  Checking HTTP response..."
if curl -s -o /dev/null -w "%{http_code}" http://localhost:8000/ | grep -q "200"; then
    echo "   ✅ Frontend accessible at http://localhost:8000/"
else
    echo "   ❌ Frontend not accessible"
    echo "      Check logs: journalctl -u fim-server -n 50"
fi
echo ""

# Check API
echo "4️⃣  Checking API..."
if curl -s http://localhost:8000/api/v1/health | grep -q "healthy"; then
    echo "   ✅ API responding at http://localhost:8000/api/v1/"
else
    echo "   ❌ API not responding"
fi
echo ""

# Check database
echo "5️⃣  Checking database..."
if sudo -u postgres psql -lqt | cut -d \| -f 1 | grep -qw fim_db; then
    echo "   ✅ Database 'fim_db' exists"
else
    echo "   ❌ Database not found"
fi
echo ""

echo "📋 Summary"
echo "=========="
echo "Frontend URL: http://$(hostname):8000/"
echo "API Docs: http://$(hostname):8000/api/docs"
echo "Dashboard: http://$(hostname):8000/dashboard"
echo ""
echo "🔐 Login with your admin credentials"
echo ""
