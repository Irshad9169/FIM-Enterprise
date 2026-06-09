# FIM Dashboard Quick Reference

## Build & Deploy
```bash
# Full deployment (build + restart)
/opt/fim/scripts/deploy-dashboard.sh

# Build only (no restart)
/opt/fim/scripts/build-frontend.sh

# Manual restart
systemctl restart fim-server

## Development Mode
# Run Next.js dev server (port 3000)
cd /opt/fim/frontend
npm run dev
# Access: http://test06:3000

Logs & Monitoring
# FIM server logs
journalctl -u fim-server -f

# Build logs
tail -f /opt/fim/scripts/build.log

# Check service status
systemctl status fim-server

Troubleshooting
Frontend not loading
# Check if web directory exists
ls -la /opt/fim/web/

# Rebuild frontend
/opt/fim/scripts/build-frontend.sh

# Check FastAPI logs
journalctl -u fim-server -n 100


API connection errors
# Check .env.local
cat /opt/fim/frontend/.env.local

# Should match your server IP/hostname
# Update if needed:
nano /opt/fim/frontend/.env.local
# Then rebuild:
/opt/fim/scripts/build-frontend.sh


CORS errors
# Check app/core/config.py
# cors_origins should include your frontend URL
# Example: cors_origins: List[str] = ["http://test06:8000", "*"]


File Locations
Frontend source: /opt/fim/frontend/
Built static files: /opt/fim/web/
Backend: /opt/fim/app/
Build script: /opt/fim/scripts/build-frontend.sh
Deploy script: /opt/fim/scripts/deploy-dashboard.sh

Port Information
FastAPI + Frontend: 8000
Development frontend: 3000 (if using npm run dev)
PostgreSQL: 5432

Updating Frontend
cd /opt/fim/frontend

# Make code changes
nano app/(dashboard)/dashboard/page.tsx

# Rebuild and deploy
/opt/fim/scripts/deploy-dashboard.sh
