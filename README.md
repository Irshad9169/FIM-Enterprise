# FIM Enterprise — File Integrity Monitoring System

[![Python](https://img.shields.io/badge/Python-3.11+-3776AB?style=for-the-badge&logo=python&logoColor=white)](https://python.org)
[![FastAPI](https://img.shields.io/badge/FastAPI-0.104+-009688?style=for-the-badge&logo=fastapi&logoColor=white)](https://fastapi.tiangolo.com)
[![React](https://img.shields.io/badge/React-18+-61DAFB?style=for-the-badge&logo=react&logoColor=black)](https://react.dev)
[![PostgreSQL](https://img.shields.io/badge/PostgreSQL-15-4169E1?style=for-the-badge&logo=postgresql&logoColor=white)](https://postgresql.org)
[![TypeScript](https://img.shields.io/badge/TypeScript-5+-3178C6?style=for-the-badge&logo=typescript&logoColor=white)](https://typescriptlang.org)

**Production-grade file integrity monitoring with real-time dashboards, RT ticket integration, and compliance reporting.**

---

## 🏗️ Architecture

```
┌────────────────────┐    ┌───────────────────────────┐    ┌──────────────┐
│   FIM Agents       │    │     FastAPI Backend        │    │ PostgreSQL   │
│   (Python 3.x)     │───→│     (Uvicorn + Async)     │───→│ 15 (asyncpg) │
│   • File scanning  │    │     • JWT + SSO Auth       │    │ • 12 tables  │
│   • SHA-256 hashing│    │     • Change detection     │    │ • JSONB data │
│   • Heartbeats     │    │     • Report generation    │    │ • Full audit │
└────────────────────┘    └───────────────────────────┘    └──────────────┘
         ↑                          ↓            ↓
         │                  ┌───────────┐  ┌──────────┐
    Monitored Servers       │  Nginx    │  │ Sendmail │
    (/etc, /opt, /var)      │  (HTTPS)  │  │ (Email)  │
                            └───────────┘  └──────────┘
                                  ↓
                        ┌───────────────────┐
                        │  React Frontend   │
                        │  • Dashboard      │
                        │  • Charts         │
                        │  • Report Mgmt    │
                        └───────────────────┘
```

---

## ✨ Features

### Core
- **Automated Daily Scans** — Agents scan at 02:00 AM, server processes changes against approved baselines
- **Real-time Dashboard** — Alert trends, severity/status donut charts, scan activity, agent health
- **Daily Report Workflow** — Generate → Review per agent → Add notes → Publish to RT
- **RT/CMR Integration** — Auto-post HTML reports as comments to Request Tracker tickets via sendmail
- **PCI-DSS Compliance Reports** — One-click PDF generation for Requirement 11.5

### Security
- **JWT Token Hardening** — Includes `iat`, `jti` (replay prevention), `iss` claims. 8-hour expiry
- **CSRF Protection** — Double-submit cookie pattern on all state-changing requests
- **Session Revocation** — Sessions revoked immediately on role/password change
- **Baseline Integrity Verification** — SHA-256 checksum validated before every comparison
- **Scan Result HMAC Signing** — Agent signs scan data with HMAC-SHA256, server verifies
- **API Rate Limiting** — Login: 5/min, scan submit: 30/min, agents: 10–120/min, general: 120/min
- **RBAC** — 4 roles: admin, analyst, trainee, auditor with granular permissions
- **Encrypted API Keys** — Agent API keys encrypted with Fernet AES-128 at rest
- **Immutable Audit Logs** — DB triggers block DELETE/UPDATE + SHA-256 hash chain
- **Structured Security Logging** — JSON security events for all 401/403/login events
- **PostgreSQL SSL** — All DB connections encrypted with TLSv1.3
- **mTLS Infrastructure** — Prepared for mutual TLS authentication (activate when ready)

### Operations
- **Baseline Re-approval Workflow** — Re-baseline with justification, old baseline preserved for audit
- **Baseline Diff Viewer** — Compare old vs new baselines (added/removed/modified files)
- **Bulk Alert Operations** — Select multiple alerts, batch acknowledge/resolve/false-positive
- **Report Auto-Generation** — Scheduler creates reports at 09:00 IST daily
- **Report Archival** — Archive reports older than N days, admin only
- **Email Notifications** — Auto-notify on report generation, critical alerts, baseline failures
- **Audit Log Export** — CSV + PDF export with configurable date range
- **Agent Tags/Groups** — Tag agents by environment (production, staging, web-tier)
- **Multi-Agent Deployment** — Shell script for remote agent deployment via SSH
- **Dark/Light Theme** — Toggle in sidebar

---

## 📁 Directory Structure

```
fim/
├── app/                                # Backend (FastAPI)
│   ├── api/                            # Route handlers
│   │   ├── agents.py                   # Agent management + tags
│   │   ├── alerts.py                   # Alerts CRUD + bulk operations
│   │   ├── audit.py                    # Audit logs + CSV/PDF export
│   │   ├── auth_enhanced.py            # Password auth + CSRF cookie
│   │   ├── auth_sso.py                 # SSO callback + CSRF cookie
│   │   ├── baselines.py                # Approval/re-baseline/diff
│   │   ├── dashboard.py                # Stats + trends + agent health
│   │   ├── exclusions.py               # Whitelist rules
│   │   ├── reports.py                  # Daily reports + compliance
│   │   ├── scans.py                    # Scan submission + size limits
│   │   ├── sessions.py                 # Session management
│   │   └── users.py                    # User CRUD + change logging
│   ├── core/                           # Configuration & security
│   │   ├── config.py                   # Pydantic settings (.env)
│   │   ├── database.py                 # Async connection pool (SSL)
│   │   ├── security.py                 # JWT + session revocation check
│   │   └── security_logger.py          # Structured JSON security events
│   ├── middleware/                      # Middleware stack
│   │   ├── csrf_middleware.py           # CSRF double-submit cookie
│   │   ├── rate_limiter.py             # IP-based rate limiting
│   │   ├── rbac.py                     # Permission enforcement
│   │   ├── request_size_limiter.py     # DoS protection (body size)
│   │   └── security_logging_middleware.py  # 401/403 auto-logging
│   ├── models/                         # SQLAlchemy ORM models
│   │   └── models.py
│   ├── services/                       # Business logic
│   │   ├── change_detector.py          # Baseline comparison engine
│   │   ├── compliance_report.py        # PCI-DSS PDF generator
│   │   ├── email_service.py            # Sendmail notifications
│   │   ├── report_scheduler.py         # Auto daily report at 09:00
│   │   ├── session_service.py          # Session DB operations
│   │   └── ticket_linker.py            # RT ticket integration
│   └── main.py                         # App + middleware stack + routers
├── agent/                              # FIM Agent
│   ├── fim_agent.py                    # Scan + heartbeat + encrypted key
│   └── config/
│       ├── agent_config.yaml           # Live config (api_key encrypted)
│       └── agent_config.yaml.example   # Template for new deployments
├── frontend/                           # React source (TypeScript + Vite)
│   └── src/
│       ├── api/
│       │   ├── client.ts               # Axios instance + CSRF interceptor
│       │   └── dashboard.ts            # All API calls + CSRF header
│       └── pages/                      # All page components
├── scripts/                            # Security hardening scripts
│   ├── gap7_request_size_limits.sh
│   ├── gap8_db_connection_encryption.sh
│   ├── gap9_encrypt_api_keys.sh
│   ├── gap10_audit_log_protection.sh
│   ├── gap11_upload_size_validation.sh
│   ├── gap12_session_fixation.sh
│   ├── gap13_csrf_protection.sh
│   ├── gap14_insufficient_logging.sh
│   ├── gap15_agent_rate_limiting.sh
│   └── gap16_backup_encryption.sh
├── web/                                # Built frontend (Nginx serves this)
├── requirements.txt                    # Python dependencies
├── .env.example                        # Environment template
└── .gitignore                          # Excludes secrets, keys, node_modules
```

---

## 🛠️ Tech Stack

| Component | Technology | Version |
|-----------|-----------|---------|
| Backend | FastAPI / Uvicorn | 0.104+ |
| Frontend | React / TypeScript / Vite | 18+ |
| Database | PostgreSQL (asyncpg) | 15+ |
| ORM | SQLAlchemy (async) | 2.0+ |
| Charts | Recharts | 2.x |
| Auth | python-jose (JWT) + SSO | — |
| Icons | Lucide React | — |
| Styling | Tailwind CSS | 3.x |
| Email | sendmail | — |
| Proxy | Nginx (HTTPS/TLS) | — |

---

## 🚀 Quick Start

```bash
# 1. Clone
git clone https://github.com/Irshad9169/FIM-Enterprise-Secure.git
cd FIM-Enterprise-Secure

# 2. Backend
python3.11 -m venv venv && source venv/bin/activate
pip install -r requirements.txt

# 3. Frontend
cd frontend
npm install
npm install date-fns        # required dependency
npm run build               # output goes to ../web/
cd ..

# 4. Database
sudo -u postgres psql << 'SQL'
CREATE USER fim_app WITH PASSWORD 'your-strong-password';
CREATE DATABASE fim_db OWNER fim_app;
GRANT ALL PRIVILEGES ON DATABASE fim_db TO fim_app;
\c fim_db
CREATE SCHEMA fim AUTHORIZATION fim_app;
SQL

# 5. Configure environment
cp .env.example .env
# Generate a strong SECRET_KEY:
python3 -c "import secrets; print(secrets.token_hex(32))"
nano .env

# 6. SSL certificate (self-signed for internal use)
mkdir -p /opt/fim/certs/ssl
openssl req -x509 -nodes -days 365 -newkey rsa:2048 \
    -keyout /opt/fim/certs/ssl/fim-server.key \
    -out    /opt/fim/certs/ssl/fim-server.crt \
    -subj "/CN=your-hostname/O=YourOrg/C=IN"

# 7. Deploy frontend to Nginx web root
mkdir -p /opt/fim/web
cp -r web/* /opt/fim/web/

# 8. Create and start systemd service
cat > /etc/systemd/system/fim-backend.service << 'EOF'
[Unit]
Description=FIM Enterprise Backend
After=network.target postgresql-15.service

[Service]
Type=simple
WorkingDirectory=/usr/local/opt/fim
ExecStart=/usr/local/opt/fim/venv/bin/uvicorn app.main:app --host 0.0.0.0 --port 8000
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
EOF

systemctl daemon-reload
systemctl enable fim-backend --now

# 9. Verify
curl -s http://localhost:8000/api/v1/health
# {"status":"healthy","service":"FIM Server"}
```

---

## 🔒 Security Hardening

Run these scripts in order on a fresh deployment:

| Script | Gap | What it fixes |
|--------|-----|---------------|
| `scripts/gap7_request_size_limits.sh` | #7 | DoS via oversized request bodies |
| `scripts/gap8_db_connection_encryption.sh` | #8 | PostgreSQL plaintext connections |
| `scripts/gap9_encrypt_api_keys.sh` | #9 | Hardcoded API keys in agent config |
| `scripts/gap10_audit_log_protection.sh` | #10 | Audit log tampering (delete/modify) |
| `scripts/gap11_upload_size_validation.sh` | #11 | Unlimited scan payload size |
| `scripts/gap12_session_fixation.sh` | #12 | Stale JWT tokens after role change |
| `scripts/gap13_csrf_protection.sh` | #13 | CSRF attacks on state-changing endpoints |
| `scripts/gap14_insufficient_logging.sh` | #14 | Missing security event logging |
| `scripts/gap15_agent_rate_limiting.sh` | #15 | Agent registration flooding |
| `scripts/gap16_backup_encryption.sh` | #16 | Plaintext database backups |

```bash
# Run all hardening scripts in sequence
for script in scripts/gap{7..16}*.sh; do
    echo "▶ Running $script..."
    sudo bash "$script"
done
```

---

## 🔑 Secret Files (Never Committed to Git)

These files must be created manually on each server and backed up securely off-server:

| File | Purpose | How to create |
|------|---------|---------------|
| `.env` | App credentials and config | `cp .env.example .env` then edit |
| `/etc/fim/agent-encrypt.key` | Fernet key for agent API key encryption | Auto-created by `gap9` script |
| `/etc/fim/backup-passphrase` | GPG passphrase for backup encryption | Auto-created by `gap16` script |
| `/opt/fim/certs/ssl/fim-server.key` | Nginx SSL private key | `openssl req ...` (see step 6) |
| `agent/config/agent_config.yaml` | Agent config with encrypted API key | `cp agent_config.yaml.example agent_config.yaml` |

---

## 🤖 Agent Deployment

```bash
# On each monitored server:
scp agent/fim_agent.py root@agent-host:/opt/fim-agent/
scp agent/config/agent_config.yaml.example \
    root@agent-host:/opt/fim-agent/config/agent_config.yaml

# Edit config on the agent host
nano /opt/fim-agent/config/agent_config.yaml
# Set: server.url, server.api_key, agent.hostname, monitored_paths

# Encrypt the API key (run gap9 on agent host)
sudo bash scripts/gap9_encrypt_api_keys.sh

# Install as a service
cat > /etc/systemd/system/fim-agent.service << 'EOF'
[Unit]
Description=FIM Agent
After=network.target

[Service]
Type=simple
ExecStart=/usr/bin/python3 /opt/fim-agent/fim_agent.py
Restart=always
RestartSec=10

[Install]
WantedBy=multi-user.target
EOF

systemctl enable fim-agent --now
```

---

## 👥 Roles & Permissions

| Permission | Admin | Analyst | Trainee | Auditor |
|-----------|-------|---------|---------|---------|
| Generate Reports | ✅ | ✅ | ❌ | ❌ |
| Review/Submit Reports | ✅ | ✅ | ✅ | ❌ |
| Publish to RT | ✅ | ✅ | ❌ | ❌ |
| Trigger Scans | ✅ | ✅ | ❌ | ❌ |
| Approve Baselines | ✅ | ✅ | ❌ | ❌ |
| Manage Alerts | ✅ | ✅ | ❌ | ❌ |
| Acknowledge Alerts | ✅ | ✅ | ✅ | ❌ |
| Manage Users | ✅ | ❌ | ❌ | ❌ |
| View Audit Logs | ✅ | ❌ | ❌ | ✅ |
| Manage Sessions | ✅ | ❌ | ❌ | ❌ |

---

## 📊 Dashboard

The dashboard displays:
- **Stat Cards** — Total alerts, open alerts, online agents, pending reports
- **Alert Trend (30 days)** — Area chart with critical/high/total breakdown
- **Open Alerts by Severity** — Donut chart (red/orange/yellow/blue)
- **All Alerts by Status** — Donut chart (open/acknowledged/resolved)
- **Scan Activity** — Bar chart with scans and changes per day
- **Agent Health** — Per-agent status cards

---

## 📋 Log Files

| Log | Purpose |
|-----|---------|
| `/var/log/fim-security.log` | Security events (login, CSRF, 401/403) in JSON |
| `/var/log/fim-audit.log` | Immutable audit trail (append-only) |
| `/var/log/fim-backup.log` | Encrypted backup job results |
| `journalctl -u fim-backend` | Application and error logs |
| `journalctl -u postgresql-15` | Database logs |

```bash
# Monitor security events in real time
tail -f /var/log/fim-security.log | python3 -m json.tool

# Detect brute-force attempts
grep login_failed /var/log/fim-security.log | \
  python3 -c "
import sys,json,collections
ips = collections.Counter(json.loads(l)['ip'] for l in sys.stdin)
print(ips.most_common(10))"

# Restore from encrypted backup
gpg --batch --passphrase-file /etc/fim/backup-passphrase \
    --decrypt /opt/fim/fim-backups/fim_backup_YYYYMMDD.dump.gpg \
    | pg_restore -d fim_db -v
```

---

## 🔐 Security Assessment Status

Based on FIM Security Analysis — May 2026:

| Severity | Total | Fixed | Remaining |
|----------|-------|-------|-----------|
| 🔴 Critical | 12 | 12 | 0 |
| 🟠 High | 8 | 5 | 3 |
| 🟡 Medium | 6 | 0 | 6 |
| 🟢 Low | 4 | 0 | 4 |

**Remaining HIGH:** GAP #17 (CSP Headers), GAP #18 (CORS config), GAP #20 (MFA)

---

## 📄 Documentation

- **API Docs (Swagger)** — `https://your-server/docs`
- **API ReDoc** — `https://your-server/redoc`

---

## 📝 License

Internal use only — *Built for enterprise security teams*

# FIM-Enterprise
