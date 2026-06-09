#!/bin/bash
# FIM System Recovery Script
# Target: PostgreSQL 15 and FIM Backend Restoration

echo "------------------------------------------------"
echo "Starting FIM System Recovery: $(date)"
echo "------------------------------------------------"

# 1. FIX USER AND GROUP IDENTITY
echo "[1/5] Verifying postgres identity..."

# Ensure group 'postgres' exists and is mapped to GID 26
if getent group postgres >/dev/null; then
    echo "  - Group 'postgres' found. Ensuring GID is 26..."
    groupmod -g 26 postgres 2>/dev/null
else
    echo "  - Group 'postgres' missing. Creating with GID 26..."
    groupadd -g 26 postgres
fi

# Ensure user 'postgres' exists and is mapped to UID 26
if id -u postgres >/dev/null 2>&1; then
    echo "  - User 'postgres' found. Ensuring UID is 26..."
    usermod -u 26 -g 26 postgres 2>/dev/null
else
    echo "  - User 'postgres' missing. Creating with UID 26..."
    useradd -u 26 -g 26 -d /var/lib/pgsql -s /bin/bash postgres
fi

# Final identity check
id postgres

# 2. FIX FILE PERMISSIONS
echo "[2/5] Repairing filesystem permissions..."
if [ -d "/var/lib/pgsql" ]; then
    chown -R postgres:postgres /var/lib/pgsql/
    chmod 700 /var/lib/pgsql/15/data/
    echo "  - /var/lib/pgsql ownership fixed."
else
    echo "  - ERROR: Database directory /var/lib/pgsql not found!"
    exit 1
fi

# 3. FIX RUNTIME DIRECTORY (Socket)
echo "[3/5] Setting up runtime socket directory..."
mkdir -p /run/postgresql
chown postgres:postgres /run/postgresql
chmod 775 /run/postgresql

# Make this persistent across reboots
echo "d /run/postgresql 0775 postgres postgres -" > /etc/tmpfiles.d/postgresql.conf
echo "  - Persistence rule added to /etc/tmpfiles.d/postgresql.conf"

# 4. RECOVERY FROM CRASH (PID cleanup)
echo "[4/5] Cleaning stale lock files..."
rm -f /var/lib/pgsql/15/data/postmaster.pid
rm -f /tmp/.s.PGSQL.5432
rm -f /tmp/.s.PGSQL.5432.lock

# 5. START SERVICES
echo "[5/5] Restarting services..."

# Start Database
echo "  - Starting PostgreSQL 15..."
systemctl daemon-reload
systemctl start postgresql-15

if systemctl is-active --quiet postgresql-15; then
    echo "  - ✅ PostgreSQL 15 is UP."
else
    echo "  - ❌ PostgreSQL 15 FAILED to start. Check 'journalctl -u postgresql-15'"
    exit 1
fi

# Start FIM Backend
echo "  - Restarting FIM Backend..."
pkill -9 -f uvicorn
cd /opt/fim
source venv/bin/activate
nohup uvicorn app.main:app --host 0.0.0.0 --port 8000 > /opt/fim/logs/uvicorn.log 2>&1 &
echo "  - ✅ FIM Backend triggered."

# Start FIM Agent
echo "  - Restarting FIM Agent..."
pkill -f fim_agent.py
cd /opt/fim/agent
nohup python3 fim_agent.py --config /opt/fim/agent/config/agent_config.yaml > logs/fim_agent.log 2>&1 &
echo "  - ✅ FIM Agent triggered."

echo "------------------------------------------------"
echo "Recovery Complete. Check Dashboard at port 8000."
echo "------------------------------------------------"
