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
- **Per-Agent API Key Auth** — Each agent authenticates with its own established key (`hmac.compare_digest` against a stored hash), not a shared secret; trust-on-first-contact on registration
- **API Rate Limiting** — Login: 5/min, scan submit: 30/min, agents: 10–120/min, general: 120/min
- **RBAC** — 4 roles: admin, analyst, trainee, auditor with granular permissions
- **Encrypted API Keys** — Agent API keys encrypted with Fernet AES-128 at rest
- **Immutable Audit Logs** — DB triggers block DELETE/UPDATE + SHA-256 hash chain
- **Tamper-Evident Alerts** — `fim.alerts` has its own append-only DB trigger (`protect_alert_evidence`); alerts can be marked `false_positive`/`resolved`/etc but never deleted, even by a superuser — closing an alert never erases the record that it fired
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
- **Remote Config Push** — Edit an agent's monitored paths/exclude patterns from the UI; agent applies it live on its next heartbeat, no restart
- **Scan Pause/Resume** — Pause a running agent scan remotely; it checkpoints and resumes rather than restarting from scratch
- **Real-Time Change Detection** — `watchdog`-based filesystem watching triggers a debounced rescan on actual change, on top of the scheduled scan (falls back to scheduled-only if `watchdog` isn't installed)
- **Incremental Scan Caching** — Unchanged files (by mtime+size) skip re-hashing; persists correctly across process restarts
- **Content Diffing** — Local unified diffs for config-shaped files (`.conf`/`.yaml`/`.json`/etc, size-capped) so a report shows *what* changed, not just that the hash did
- **Auditd Correlation** — For a curated critical-path list, attributes a detected change to the uid/process/command via `ausearch`
- **Agent Self-Integrity Reporting** — Agent hashes its own running script and reports it every heartbeat; server alerts once on a mismatch (e.g. a reverted or tampered script)
- **System Health Dashboard** — Disk usage and top Postgres table sizes, with admin-configurable warning/critical thresholds (sliders, not a hardcoded value) and a sidebar badge visible from any page

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
│   │   ├── anomalies.py                # Anomaly scores (volume spikes, repeated mods)
│   │   ├── baselines.py                # Approval/re-baseline/diff
│   │   ├── dashboard.py                # Stats + trends + agent health
│   │   ├── exclusions.py               # Whitelist rules
│   │   ├── reports.py                  # Daily reports + compliance
│   │   ├── scans.py                    # Scan submission + size limits
│   │   ├── sessions.py                 # Session management
│   │   ├── system.py                   # Disk/DB health + configurable thresholds
│   │   ├── users.py                    # User CRUD + change logging
│   │   ├── mfa.py                      # MFA (built, NOT mounted — see Security Hardening below)
│   │   └── agents_enhanced.py, scan_requests.py  # Written, NOT mounted — dead code today
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
│   │   ├── change_detector.py          # Baseline comparison engine (dedup by fingerprint,
│   │   │                               #   not just "currently open" — see CHANGELOG)
│   │   ├── compliance_report.py        # PCI-DSS PDF generator
│   │   ├── email_service.py            # Sendmail notifications
│   │   ├── anomaly_detector.py         # Alert-volume/repeated-mod scoring (GAP #19)
│   │   ├── report_scheduler.py         # Auto daily report at 09:00 IST
│   │   ├── report_generator.py         # NOT used by report_scheduler — dead code, see report_scheduler._generate_report instead
│   │   ├── session_service.py          # Session DB operations
│   │   └── ticket_linker.py            # RT ticket integration
│   ├── db/migrations/versions/         # Alembic — the live migration mechanism (NOT database/migrations/, see below)
│   └── main.py                         # App + middleware stack + routers
├── agent/                              # FIM Agent
│   ├── fim_agent.py                    # Scan + heartbeat + real-time watch + incremental cache
│   └── config/
│       ├── agent_config.yaml           # Live config (api_key encrypted)
│       └── agent_config.yaml.example   # Template for new deployments
├── frontend/                           # React source (TypeScript + Vite)
│   └── src/
│       ├── api/
│       │   ├── client.ts               # Axios instance + CSRF interceptor
│       │   └── dashboard.ts            # All API calls + CSRF header
│       └── pages/                      # All page components, incl. SystemHealthPage.tsx
├── scripts/                            # Security hardening (gap*.sh) + operational scripts
│   ├── gap7_request_size_limits.sh … gap23_baseline_diff_signing.sh  # see Security Hardening below
│   ├── cleanup_scan_data.sh            # fim.scans retention (30d null payload / 3mo full delete) + VACUUM
│   └── fim-disk-cleanup.sh             # Daily disk hygiene; also invokes cleanup_scan_data.sh
├── database/migrations/                # Legacy — 2 incremental SQL patch files only, NOT a full
│   │                                    #   schema, NOT where new migrations go (see app/db/migrations/)
├── web/                                # Built frontend (Nginx serves this)
├── requirements.txt                    # Python dependencies
├── .env.example                        # Environment template
└── .gitignore                          # Excludes secrets, keys, node_modules
```

⚠️ **Migrations live in `app/db/migrations/versions/` (Alembic), not `database/migrations/`.**
The latter has exactly two old SQL patch files and isn't maintained. Run `alembic upgrade
head` after every `git pull` that touches models — see `docs/PRODUCTION_DEPLOYMENT.md` §4.

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
| `scripts/gap16_backup_encryption.sh` | #16 | Plaintext database backups (⚠️ see [PRODUCTION_DEPLOYMENT.md §13](docs/PRODUCTION_DEPLOYMENT.md) before scheduling this — its default retention can exceed available disk on a small volume) |
| `scripts/gap17_csp_headers.sh` | #17 | Missing Content-Security-Policy headers |
| `scripts/gap18_cors_configuration.sh` | #18 | CORS — note `app/main.py`'s `allow_origins` is still hardcoded regardless; this script doesn't make `.env`'s `CORS_ORIGINS` live |
| `scripts/gap19_anomaly_detection.sh` | #19 | Anomaly detection engine (alert-volume spikes, repeated-modification patterns) |
| `scripts/gap21_baseline_version_control.sh` | #21 | Baseline change history (git-backed) — hardcodes `/opt/fim/baselines-git`, not `FIM_HOME`-aware |
| `scripts/gap22_mtls_activation.sh` | #22 | Mutual TLS between agent and server |
| `scripts/gap23_baseline_diff_signing.sh` | #23 | Signed baseline diffs |

*(GAP #20 — MFA — has backend/frontend code already written (`app/api/mfa.py`, `app/core/mfa.py`, `frontend/src/pages/MFASettingsPage.tsx`) but neither is wired in: the router isn't mounted in `app/main.py` and the page isn't routed in `App.tsx`. It's not "not built," it's built and disconnected.)*

```bash
# Run all hardening scripts in sequence (skips #20, which has no script — see note above)
for script in scripts/gap{7..23}*.sh; do
    [ -f "$script" ] || continue
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
| `/var/log/fim-disk-cleanup.log` | Daily disk hygiene run (backup rotation, pycache, `cleanup_scan_data.sh`, journal/log trims) |
| `journalctl -u fim-backend` | Application and error logs |
| `journalctl -u postgresql-15` | Database logs |

Also worth checking in the app itself rather than a log file: **System Health**
(Administration → System Health, admin-only) shows live disk usage and the largest
Postgres tables by size — this is what would have caught `fim.scans` growing to 27GB
before it took the disk to 0 bytes free (see CHANGELOG). Its warning/critical
thresholds are admin-configurable there, not hardcoded.

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

16 of the 17 numbered GAP fixes in the #7–#23 range have a dedicated script in
`scripts/` — see the Security Hardening table above for what each one covers. The
exception is GAP #20 (MFA), which has the application code written but not wired
into the running app (see the note above the table) — that's the one real gap left
to close, not a missing feature.

This status is kept here only as a one-line summary. For the actual, currently-accurate
list of what's fixed, what's still dead code, and non-obvious deployment gotchas
(hardcoded CORS origins, `SECRET_KEY` env-loading trap, etc.), see
**[`docs/PRODUCTION_DEPLOYMENT.md`](docs/PRODUCTION_DEPLOYMENT.md)** — that doc is the one
actively updated when something real is found; this README is not.

---

## 📄 Documentation

- **API Docs (Swagger)** — `https://your-server/docs`
- **API ReDoc** — `https://your-server/redoc`
- **[docs/PRODUCTION_DEPLOYMENT.md](docs/PRODUCTION_DEPLOYMENT.md)** — actively-maintained deployment guide, written from real cutover/troubleshooting work, not just theory. Read this before deploying to a new server.
- **[docs/CHANGELOG.md](docs/CHANGELOG.md)** — what actually changed and why
- **[docs/ARCHITECTURE.md](docs/ARCHITECTURE.md)** — high-level system diagrams (⚠️ predates several features above — directionally useful, not authoritative on current detail)

---

## 📝 License

Internal use only — *Built for enterprise security teams*

# FIM-Enterprise
