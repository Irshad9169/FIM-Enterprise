#!/bin/bash
set -e

echo "🚀 Deploying FIM Dashboard"
echo "=========================="
echo ""

# Step 1: Build frontend
echo "📦 Step 1/3: Building frontend..."
/opt/fim/scripts/build-frontend.sh
echo ""

# Step 2: Check if fim-server is running
echo "🔍 Step 2/3: Checking FIM server status..."
if systemctl is-active --quiet fim-server; then
    echo "   FIM server is running"
    echo "   Restarting to load new frontend..."
    systemctl restart fim-server
    sleep 2
    
    if systemctl is-active --quiet fim-server; then
        echo "   ✅ FIM server restarted successfully"
    else
        echo "   ❌ FIM server failed to restart"
        systemctl status fim-server --no-pager
        exit 1
    fi
else
    echo "   ⚠️  FIM server not running, starting..."
    systemctl start fim-server
    sleep 2
    
    if systemctl is-active --quiet fim-server; then
        echo "   ✅ FIM server started successfully"
    else
        echo "   ❌ FIM server failed to start"
        systemctl status fim-server --no-pager
        exit 1
    fi
fi
echo ""

# Step 3: Display access info
echo "🎉 Step 3/3: Deployment complete!"
echo ""
echo "📊 Dashboard Access:"
echo "   URL: http://test06:8000/"
echo "   API: http://test06:8000/api/v1/"
echo "   Docs: http://test06:8000/api/docs"
echo ""
echo "🔐 Login Credentials:"
echo "   Use your admin credentials created earlier"
echo ""
echo "📝 Logs:"
echo "   journalctl -u fim-server -f"
echo ""
