# FIM Enterprise — Production Deployment Guide

This guide reflects lessons learned from real cutover/troubleshooting work on this
codebase, not just the theoretical install steps. Several things in this app look
configurable but silently aren't — those are called out explicitly (⚠️) so a new
deployment doesn't quietly inherit the same gaps.

Target OS: RHEL/CentOS/Rocky family (scripts fall back to `apt-get` where relevant,
but `yum`/`dnf` is the primary path this repo assumes).

---

## 0. Before you start — decisions to make

- **Install path**: everything below assumes `/opt/fim`. Several source files hardcode
  this as a *fallback* default via a `FIM_HOME` environment variable (see §6) — if you
  use a different path, you must set `FIM_HOME` explicitly everywhere the app runs.
- **Service user**: this repo has two systemd unit templates with different conventions
  — `fim-backend.service` (root, single worker) and `fim-server.service` (`secauto` user,
  4 workers). Pick one style and use it consistently; this guide uses the `secauto` /
  multi-worker pattern as the recommended production template, but check what your
  existing servers actually run and match it if consistency across your fleet matters.

---

## 1. System prerequisites

```bash
sudo yum install -y python3.11 python3.11-venv git nginx postfix openssl gnupg2

# PostgreSQL 15 (from the PGDG repo if not already configured)
sudo yum install -y postgresql15-server postgresql15
sudo /usr/pgsql-15/bin/postgresql-15-setup initdb
sudo systemctl enable postgresql-15 --now

# Node.js (check an existing working server for the exact major version in use —
# this repo has no package.json "engines" field pinning one)
sudo yum install -y nodejs npm
```
Ensure `sendmail` works as a local MTA (Postfix provides `/usr/sbin/sendmail`) —
see §8, this is how the app actually sends email, not via any SMTP env var.

---

## 2. Create the service user and install directory

```bash
sudo useradd -r -s /sbin/nologin secauto || true
sudo mkdir -p /opt/fim
sudo chown secauto:secauto /opt/fim
```

---

## 3. Clone the code

```bash
cd /opt
sudo -u secauto git clone https://github.com/Irshad9169/FIM-Enterprise.git fim
cd /opt/fim
sudo -u secauto git checkout feature/upgrades   # or whichever branch is production-ready
```
⚠️ If you clone with a URL rather than specifying the target directory name, git will
create a subfolder named after the repo (e.g. `fim/FIM-Enterprise/`) rather than cloning
directly into `fim/`. Use `git clone <url> /opt/fim` (trailing directory name) to avoid
the extra nesting level, or account for it in every path below if you don't.

---

## 4. Database — provision from an existing instance, not from scratch

⚠️ **This repo does not contain a from-scratch schema file.** `database/migrations/`
only has two *incremental* patch files (`001_phase1_schema.sql`, `002_report_workflow_corrected.sql`)
that `ALTER` tables assumed to already exist (`fim.users`, `fim.agents`, `fim.scans`,
`fim.alerts`, `fim.baselines`, etc.) — those base tables were created ad hoc during
initial development and were never captured as a versioned migration. Do **not** try
to build a new database by running the migration files against an empty schema —
they will fail (and `001_phase1_schema.sql` opens with `\c fim_db`, a hardcoded psql
command that reconnects to whatever database is literally named `fim_db` regardless
of what you're connected to — dangerous if run carelessly near a real `fim_db`).

**The reliable method:** dump the schema (and data, if you want to seed real content)
from a working instance and restore it on the new server.

```bash
# On an existing working server:
sudo -u postgres pg_dump -Fc fim_db -f /tmp/fim_db.dump
scp /tmp/fim_db.dump new-server:/tmp/

# On the new server:
sudo -u postgres psql << 'SQL'
CREATE USER fim_app WITH PASSWORD 'a-new-strong-password';
CREATE DATABASE fim_db OWNER fim_app;
SQL
sudo -u postgres pg_restore -d fim_db /tmp/fim_db.dump
```
If you truly need to start with zero data (e.g. this is a brand-new deployment with
no existing instance to dump from), you'll need to hand-build the schema by cross-
referencing `app/models/models.py`'s SQLAlchemy models against `database/migrations/`
— there's no shortcut for this today. Consider generating and committing a proper
`000_initial_schema.sql` via `pg_dump --schema-only` from a working instance as a
follow-up improvement so future deployments don't hit this gap.

Enable SSL on the Postgres connection per the README's existing guidance
(`sslmode=require` in `DATABASE_URL`, TLS cert configured in `postgresql.conf`).

---

## 5. Python backend

```bash
cd /opt/fim
sudo -u secauto python3.11 -m venv venv
sudo -u secauto venv/bin/pip install -r requirements.txt
```

### `.env`
```bash
sudo -u secauto cp .env.example .env
```
Edit `/opt/fim/.env`:
```bash
DATABASE_URL=postgresql+asyncpg://fim_app:<password-from-step-4>@localhost/fim_db
SECRET_KEY=$(python3 -c "import secrets; print(secrets.token_hex(32))")
```
Fill in `SMTP_*` if you like for documentation purposes, but see §8 — they do nothing.
Fill in `CORS_ORIGINS` too for documentation purposes, but see §7 — it also does nothing
at runtime; the real value is hardcoded in source and must be edited there.

Optional — RT/CMR/JIRA ticket-system integration (these ARE live via `Settings`,
unlike `SMTP_*`/`CORS_ORIGINS` above — safe to omit, defaults match the original
hardcoded RT/CMR URLs so nothing changes unless you override them):
```bash
RT_LOOKUP_URL=http://rtapi.int.untd.com/cgi-bin/rt.cgi
RT_UPDATE_URL=https://rtapi.int.untd.com/cgi-bin/rt.cgi
RT_EMAIL=security@tickets.int.untd.com
CMR_URL=https://phantom.int.untd.com/bin/phantom
# JIRA is net-new and disabled by default (empty JIRA_URL = no-op). Set all
# three to enable; jira_email present -> Basic auth, absent -> Bearer token.
JIRA_URL=
JIRA_EMAIL=
JIRA_API_TOKEN=
```

⚠️ **`.env` alone is not enough** — several values (`SECRET_KEY`, `JWT_ALGORITHM`,
`ACCESS_TOKEN_EXPIRE_MINUTES`, `REPORT_AUTO_GENERATE`, `REPORT_SCHEDULE_HOUR`,
`REPORT_SCHEDULE_MINUTE`) are read via `os.getenv()` directly in `app/core/security.py`
and `app/services/report_scheduler.py`, bypassing the pydantic `Settings` class that
actually loads `.env`. Unless `.env` is also loaded as real **process** environment
variables, these all silently fall back to hardcoded defaults —
`SECRET_KEY` falls back to the literal string `"your-secret-key-change-in-production"`,
a live authentication bypass if missed. **The systemd unit must include:**
```ini
EnvironmentFile=/opt/fim/.env
```
This is non-optional. See §9 for the full unit file with this included.

---

## 6. Runtime support files (`FIM_HOME`)

Several features read fixed files relative to `FIM_HOME` (defaults to `/opt/fim` if
the env var isn't set — see commit `0950743` on `feature/upgrades`):

| Path | Purpose | Required? |
|---|---|---|
| `$FIM_HOME/.env` | app config | Yes |
| `$FIM_HOME/web/` | built frontend (§7) | Yes |
| `$FIM_HOME/config/sso-public.pem` | SSO login public key | Only if `SSO_ENABLED=true` |
| `$FIM_HOME/baselines-git/` | baseline version-history git repo | Only if using baseline diff/versioning (GAP #21) |
| `$FIM_HOME/email_map.conf` | RT ticket email resolution (SSO username → email) | Only if RT integration used |

If deploying at the default `/opt/fim` path, nothing needs to be set — this is
automatic. If deploying somewhere else, export `FIM_HOME=/your/path` in the systemd
unit's `Environment=` line and create these files/folders there yourself.

To activate baseline version control fresh: `bash scripts/gap21_baseline_version_control.sh`
(review it first — it hardcodes `/opt/fim/baselines-git` itself, not `FIM_HOME`-aware).

---

## 7. Frontend

```bash
cd /opt/fim/frontend
sudo -u secauto npm install --legacy-peer-deps
```
⚠️ Plain `npm install` will fail here — `package.json` pins `vite: "^8.0.12"` but
`@vitejs/plugin-react@^4.2.1`'s peer range only covers vite `^4`–`^7`. `--legacy-peer-deps`
works around it without needing a `package.json` change; the actual build works fine
despite the version mismatch.

```bash
sudo -u secauto npm run build   # outputs to /opt/fim/web (vite.config.ts: build.outDir = '../web')
```

⚠️ **CORS origins are hardcoded in `app/main.py`**, not read from `.env`'s
`CORS_ORIGINS`:
```python
allow_origins=['https://test06.hyd.int.untd.com', 'http://test06.hyd.int.untd.com',
               'http://localhost:5173', 'http://localhost:3000', 'http://localhost:8080'],
```
You **must** edit this list in `app/main.py` to include your new server's actual
hostname(s), or the browser will silently block every API call with a CORS error.
This is a required manual code edit per deployment, not a config toggle.

---

## 8. Email

⚠️ The `SMTP_*` values in `.env` are unused — `app/services/email_service.py` sends
mail via the local `/usr/sbin/sendmail` binary directly, not SMTP. Out of scope for
this guide; revisit if/when email notifications are actually needed.

---

## 9. systemd unit — backend

```bash
sudo tee /etc/systemd/system/fim-backend.service << 'EOF'
[Unit]
Description=FIM Enterprise Backend
After=network.target postgresql-15.service

[Service]
Type=simple
User=secauto
Group=secauto
WorkingDirectory=/opt/fim
Environment="PATH=/opt/fim/venv/bin"
EnvironmentFile=/opt/fim/.env
ExecStart=/opt/fim/venv/bin/uvicorn app.main:app --host 0.0.0.0 --port 8000 --workers 4
Restart=always
RestartSec=10

[Install]
WantedBy=multi-user.target
EOF

sudo systemctl daemon-reload
sudo systemctl enable fim-backend --now
curl -s http://localhost:8000/api/v1/health
# {"status":"healthy","service":"FIM Server"}
```
Verify `.env` actually loaded:
```bash
cat /proc/$(systemctl show fim-backend -p MainPID --value)/environ | tr '\0' '\n' | grep -c SECRET_KEY
# must print 1
```

---

## 10. SSL certificate + nginx

```bash
sudo mkdir -p /opt/fim/certs/ssl
sudo openssl req -x509 -nodes -days 365 -newkey rsa:2048 \
    -keyout /opt/fim/certs/ssl/fim-server.key \
    -out    /opt/fim/certs/ssl/fim-server.crt \
    -subj "/CN=your-new-hostname/O=YourOrg/C=IN"
```

There's no nginx config committed to this repo — the current server's must have been
hand-configured. Template:
```nginx
server {
    listen 443 ssl;
    server_name your-new-hostname;

    ssl_certificate     /opt/fim/certs/ssl/fim-server.crt;
    ssl_certificate_key /opt/fim/certs/ssl/fim-server.key;
    ssl_protocols TLSv1.2 TLSv1.3;

    root /opt/fim/web;
    index index.html;

    location /api/ {
        proxy_pass http://127.0.0.1:8000;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
    }

    location / {
        try_files $uri $uri/ /index.html;
    }
}

server {
    listen 80;
    server_name your-new-hostname;
    return 301 https://$host$request_uri;
}
```
```bash
sudo nginx -t && sudo systemctl reload nginx
```

---

## 11. Security hardening scripts

Run in order on a fresh deployment (review each before running — several assume
`/opt/fim` literally, not `FIM_HOME`):
```bash
cd /opt/fim
for script in scripts/gap{7..23}*.sh; do
    echo "▶ Running $script..."
    sudo bash "$script"
done
```
GAP #17 (CSP headers), #18 (CORS — see §7, still needs the manual `main.py` edit
regardless of this script), #19 (anomaly detection), #21 (baseline version control),
#22 (mTLS activation), #23 (baseline diff signing) are the newer ones not mentioned
in the top-level README — check each script's header comment for what it does before
running blind.

---

## 12. Agent deployment (per monitored server)

```bash
scp agent/fim_agent.py agent/config/agent_config.yaml.example root@monitored-host:/opt/fim-agent/
ssh root@monitored-host
cd /opt/fim-agent
mv agent_config.yaml.example config/agent_config.yaml
vi config/agent_config.yaml
# Set: server.url (https://your-new-hostname), server.api_key, agent.hostname, monitored_paths
sudo bash scripts/gap9_encrypt_api_keys.sh    # encrypts the API key in place

# Base dependencies (required — cryptography is needed to decrypt the
# gap9-encrypted api_key above; fim_agent.py imports it lazily only when
# it actually sees a "+ENC++" value, but the encrypt step above means
# every real deployment needs it):
python3 -m pip install --quiet requests pyyaml cryptography
# Real-time detection (in addition to the scheduled scan) needs watchdog.
# Optional — the agent falls back to scheduled-scan-only if this isn't
# installed, so it's safe to skip and add later.
python3 -m pip install --quiet watchdog
# If this host's Python blocks system-wide pip installs ("externally
# managed environment"), use a venv instead and point ExecStart below at
# its python: python3 -m venv venv && venv/bin/pip install requests pyyaml watchdog

sudo tee /etc/systemd/system/fim-agent.service << 'EOF'
[Unit]
Description=FIM Enterprise Agent
After=network.target

[Service]
User=root
WorkingDirectory=/opt/fim-agent
ExecStart=/usr/bin/python3 /opt/fim-agent/fim_agent.py --config /opt/fim-agent/config/agent_config.yaml
Restart=always
RestartSec=10

[Install]
WantedBy=multi-user.target
EOF

systemctl daemon-reload
systemctl enable fim-agent --now
```

**inotify watch limits (real-time detection):** watchdog uses one inotify watch
per *directory* under each monitored path, not per file, so this scales with
directory count rather than file count — comfortably below Linux's usual
default for the directory counts seen so far in this deployment, but confirm
before relying on it:

```bash
cat /proc/sys/fs/inotify/max_user_watches
find /etc /opt /var/www -type d | wc -l   # adjust to your actual monitored paths
# If the directory count is anywhere close to the limit, raise it:
echo "fs.inotify.max_user_watches=524288" | sudo tee /etc/sysctl.d/99-fim-agent.conf
sudo sysctl --system
```

**Process/user attribution via auditd (optional):** for a curated list of
high-value files — not the whole monitored tree, auditd has a rule-count limit
and blanket watches over tens of thousands of files would be both infeasible
and noisy — the agent can correlate a detected change back to the user/process
that made it, via `ausearch`.

Prerequisite check — this whole feature is a no-op (fields stay null) if
auditd isn't installed, nothing else breaks:
```bash
systemctl status auditd
```

If it is, provision watch rules for whichever critical paths you want
attribution on:
```bash
auditctl -w /etc/passwd -p wa -k fim_watch
auditctl -w /etc/shadow -p wa -k fim_watch
auditctl -w /etc/sudoers -p wa -k fim_watch
auditctl -w /etc/ssh/sshd_config -p wa -k fim_watch
# Make these survive a reboot:
cat <<'RULES' | sudo tee /etc/audit/rules.d/fim-watch.rules
-w /etc/passwd -p wa -k fim_watch
-w /etc/shadow -p wa -k fim_watch
-w /etc/sudoers -p wa -k fim_watch
-w /etc/ssh/sshd_config -p wa -k fim_watch
RULES
augenrules --load
```

Then list the same paths in `agent_config.yaml` under `monitoring`:
```yaml
monitoring:
  audit_critical_paths:
    - /etc/passwd
    - /etc/shadow
    - /etc/sudoers
    - /etc/ssh/sshd_config
```

Requires the agent to read `/var/log/audit/audit.log` (via `ausearch`) —
the checked-in `fim-agent.service` unit already runs as `root`, which has
this by default. Correlation only runs for a critical-path file whose
content the agent itself detects changed since its own last scan (not on
first sight, not for every scan of an unchanged file), so it only fires
when there's actually something new to attribute.

If a monitored root can't be watched (permission denied, watch limit hit),
`fim_agent.py` logs a warning for that root specifically and continues
scanning it on the scheduled interval only — it doesn't affect other roots
or crash the agent.

---

## 13. Backups

```bash
sudo bash scripts/setup_backups.sh          # cron + GPG passphrase for encrypted backups
sudo bash scripts/gap16_backup_encryption.sh
```
Verify the cron entry exists and a manual run succeeds:
```bash
sudo bash scripts/backup-complete-fim-local.sh
```

---

## 14. Post-deploy validation checklist

- [ ] `curl -s https://your-new-hostname/api/v1/health` → healthy
- [ ] `grep -c SECRET_KEY` on the running process's `/proc/<pid>/environ` → `1`
- [ ] Log into the dashboard in a browser — confirm no CORS errors in devtools console
- [ ] Trigger a manual scan from one connected agent, confirm it shows in the dashboard
- [ ] Generate a daily report manually, confirm email notification arrives (tests
      both the report pipeline and the local `sendmail` MTA config)
- [ ] `sudo bash scripts/verify_phase1.sh` and `verify_phase2.sh` (or
      `verify_phase2_deployment.sh`) — repo-provided smoke tests
- [ ] Confirm `/opt/fim/.env` is not world-readable: `chmod 600 /opt/fim/.env`
- [ ] Rotate the DB password used in `DATABASE_URL` if it was copied from another
      environment rather than freshly generated (see §4)

---

## Appendix: known gaps to fix upstream (not blockers, but worth doing)

- No `000_initial_schema.sql` — every fresh deployment currently depends on dumping
  an existing instance (§4). Worth generating one and committing it.
- `CORS_ORIGINS` in `.env`/`config.py` is dead code — either wire `app/main.py` to
  actually read `settings.cors_origins`, or remove the setting from `.env.example`
  to stop it looking configurable.
- `SMTP_*` settings in `.env.example`/`config.py` are dead code for the same reason —
  either wire `email_service.py` to use them as an SMTP fallback, or remove them.
- `SECRET_KEY`/`JWT_ALGORITHM`/`ACCESS_TOKEN_EXPIRE_MINUTES`/`REPORT_*` reading via
  `os.getenv()` instead of the `Settings` object is fragile — works today only because
  `EnvironmentFile=` is now wired into the systemd unit, but a future refactor that
  forgets this will silently reintroduce the auth bypass this guide had to fix live.
  Worth consolidating onto `settings.*` everywhere.
- `scripts/gap21_baseline_version_control.sh` hardcodes `/opt/fim/baselines-git`
  rather than respecting `FIM_HOME`.
