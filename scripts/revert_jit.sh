#!/bin/bash
BKP_DIR="/opt/fim/backups/pre_jit_$(date +%Y%m%d)"

echo "🔄 Reverting JIT changes..."
cp $BKP_DIR/reports.py /opt/fim/app/api/reports.py
cp $BKP_DIR/sso_manager.py /opt/fim/app/core/sso_manager.py
cp $BKP_DIR/daily_report.py /opt/fim/app/schemas/daily_report.py
cp $BKP_DIR/ReportDetailPage.tsx /opt/fim/frontend/src/pages/ReportDetailPage.tsx

# Delete the new service file to prevent import errors
rm -f /opt/fim/app/services/ticket_linker.py

echo "♻️ Restarting Backend..."
pkill -9 -f uvicorn
cd /opt/fim
source venv/bin/activate
nohup uvicorn app.main:app --host 0.0.0.0 --port 8000 > /opt/fim/logs/uvicorn.log 2>&1 &

echo "🏗️ Rebuilding Frontend..."
cd /opt/fim/frontend
npm run build

echo "✅ System reverted to working state."
