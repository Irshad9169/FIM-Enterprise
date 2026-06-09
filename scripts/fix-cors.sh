#!/bin/bash
set -e

echo "🔧 Fixing CORS Issue"
echo "===================="
echo ""

# Step 1: Update frontend to use relative API URL
echo "1️⃣  Updating frontend .env.local..."
cat > /opt/fim/frontend/.env.local << 'ENVEOF'
NEXT_PUBLIC_API_URL=/api/v1
NEXT_PUBLIC_APP_NAME=FIM Dashboard
ENVEOF
echo "   ✅ Updated to use relative API URL"
echo ""

# Step 2: Rebuild frontend
echo "2️⃣  Rebuilding frontend..."
cd /opt/fim/frontend
rm -rf /opt/fim/web/*
npm run build > /tmp/build.log 2>&1
if [ $? -eq 0 ]; then
    echo "   ✅ Build successful"
else
    echo "   ❌ Build failed, check /tmp/build.log"
    exit 1
fi
echo ""

# Step 3: Restart server
echo "3️⃣  Restarting FIM server..."
systemctl restart fim-server
sleep 3
echo "   ✅ Server restarted"
echo ""

# Step 4: Test
echo "4️⃣  Testing..."
status=$(curl -s -o /dev/null -w "%{http_code}" http://localhost:8000/login/)
if [ "$status" = "200" ]; then
    echo "   ✅ Frontend accessible"
else
    echo "   ❌ Frontend not accessible (status: $status)"
fi

api_status=$(curl -s http://localhost:8000/api/v1/health | grep -o "healthy")
if [ "$api_status" = "healthy" ]; then
    echo "   ✅ API accessible"
else
    echo "   ❌ API not accessible"
fi

echo ""
echo "🎉 Done! Try logging in again:"
echo "   http://test06.hyd.int.untd.com:8000/login"
echo ""
echo "📝 Credentials:"
echo "   Username: admin"
echo "   Password: admin123"
echo ""
