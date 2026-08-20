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
- **Service user**: fixed 2026-08-20 — `etc/systemd/system/fim-backend.service` is now
  the one canonical template (`secauto` user, 4 workers, `EnvironmentFile=`, matching §9
  exactly); the conflicting duplicate (`fim-server.service`, different name/user/worker
  count) is archived at `archive/etc-fim-server.service`. If any existing server in your
  fleet was set up from the old `fim-server`-named or root/1-worker variant, it won't
  match this template until re-deployed — check what's actually running before assuming
  consistency.

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

## 4. Database — `alembic upgrade head` now bootstraps a fresh DB

Update 2026-08-20: two new migrations close the from-scratch-schema gap
completely — all 33 real tables now get created by `alembic upgrade head`
against a genuinely empty database, no `pg_dump`/`pg_restore` required.

- **`0000_initial_schema`** creates the `fim` schema and 24 tables: all 22
  SQLAlchemy-modeled tables (generated mechanically from the live ORM
  metadata, not hand-typed) plus 2 of the 11 previously-unmodeled raw-SQL
  tables (`correlation_groups`, `anomaly_scores`, whose DDL already existed
  verbatim elsewhere in-repo). Inserted as the new root of the chain
  (`down_revision=None`).
- **`0014_unmanaged_tables_dump`** creates the remaining 9 (`sessions`,
  `agent_health_events`, `whitelist_matches`, `file_changes`,
  `baseline_history`, `retention_policies`, `api_keys`,
  `integration_settings`, `scans_archive`) — these had no CREATE TABLE
  anywhere in this repo's history at all, so this is a verbatim schema-only
  `pg_dump` from the live `fim_db` on test06, not a guess. Two things that'd
  otherwise look like mistakes: `scans_archive` genuinely has no primary key
  or index in production, and `file_changes.scan_id` has no FK to `fim.scans`
  despite the name — both faithfully preserved as-is rather than "fixed."

The `fim_app` role and `fim_db` database itself are **not** created by any
migration — Alembic connects to an already-existing, empty database, it doesn't
create the database itself. Create both first:
```bash
sudo -u postgres psql << 'SQL'
CREATE USER fim_app WITH PASSWORD 'a-new-strong-password';
CREATE DATABASE fim_db OWNER fim_app;
SQL
```
Then, from the Python backend's venv (§5 — needs `requirements.txt` installed
and `DATABASE_URL` set in `.env` first; skip ahead to §5 and come back here if
doing this in order):
```bash
cd /opt/fim
venv/bin/alembic upgrade head
```
now creates the schema, all 33 tables, and every trigger (`protect_alert_evidence`,
`raise_audit_immutable`) from nothing. Existing instances (already stamped past
`0001`) are unaffected either way — Alembic only walks forward from the current
revision, so it never attempts to re-run `0000` against a database that already
has these tables, and picks up `0014` as a normal forward step.

**Verified 2026-08-20 on test06** against a genuinely empty `fim_fresh_test`
database: `alembic upgrade head` ran the full `0000`→`0013` chain cleanly and
`\dt fim.*` came back with exactly 25 relations (24 tables + `alembic_version`),
`alembic_version` correctly at `0013_audit_log_immutability`. One real bug was
caught and fixed during that validation — `env.py`'s `CREATE SCHEMA` call needs
its own explicit `connection.commit()` before Alembic's own transaction begins,
otherwise the whole batch (all 14 migrations) gets silently rolled back on
connection close with no visible error (every "Running upgrade" line still logs
successfully, which is what makes it easy to miss). To re-run this validation
yourself:
```bash
sudo -u postgres psql -c "CREATE DATABASE fim_fresh_test OWNER fim_app;"
DATABASE_URL="postgresql+asyncpg://fim_app:<password>@localhost/fim_fresh_test" \
    venv/bin/alembic upgrade head
sudo -u postgres psql -d fim_fresh_test -c "\dt fim.*"   # expect 25 rows (24 tables + alembic_version)
sudo -u postgres psql -c "DROP DATABASE fim_fresh_test;" # clean up once confirmed
```

**Alternative: provision from an existing instance** (still the only option if you
want real seed data, or need the 9 not-yet-migrated tables today):
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

⚠️ **`database/migrations/` (2 old SQL patch files) is not where ongoing schema
changes live** — they're now fully superseded by `0000_initial_schema` and kept
only for history. The real, actively-maintained migration chain is Alembic, at
`app/db/migrations/versions/` (currently `0000`–`0013`). After restoring/dumping
the base schema above, catch up on everything since:
```bash
cd /opt/fim
venv/bin/alembic upgrade head
```
Run this after every `git pull` that touched `app/models/models.py` or added a new
`versions/*.py` file — it's easy to forget since nothing fails loudly if you don't,
until a feature that depends on the new column/table silently breaks. Also check
table **ownership** after restoring from a dump made by a different bootstrap process
— several tables (`fim.scans`, `fim.alerts` seen live) ended up owned by `postgres`
rather than `fim_app`, which blocks Alembic's `ALTER TABLE` migrations with
`InsufficientPrivilegeError: must be owner of table`. Fix per-table as found:
```sql
ALTER TABLE fim.<table> OWNER TO fim_app;
```

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

~~⚠️ `.env` alone is not enough~~ — fixed 2026-08-20: `SECRET_KEY`, `ALGORITHM`
(previously misread as the nonexistent `JWT_ALGORITHM` — that naming mismatch is
also fixed), `ACCESS_TOKEN_EXPIRE_MINUTES`, `REPORT_AUTO_GENERATE`,
`REPORT_SCHEDULE_HOUR`, and `REPORT_SCHEDULE_MINUTE` now all read from the
`Settings` object (`app/core/config.py`) instead of bare `os.getenv()` calls in
`app/core/security.py`/`app/services/report_scheduler.py`. `Settings` loads
`.env` directly regardless of whether it's also exported as real process
environment — so a plain `.env` file at `$FIM_HOME/.env` is genuinely sufficient
now, and a missing `SECRET_KEY` fails loudly at startup (`pydantic.ValidationError`)
instead of silently signing tokens with a hardcoded fallback string.
`EnvironmentFile=/opt/fim/.env` in the systemd unit (§9) is still good practice —
some other tooling may still expect real process env vars — but it is no longer
the only thing standing between a working `.env` and a live auth bypass.

### Create the first admin user

Added 2026-08-20 — every path in `app/api/users.py`'s `create_user` requires an
existing admin (`current_user.role == "admin"`), which is correct day-to-day but
leaves no way to create the very first user through the API on a genuinely empty
`fim.users` table. `scripts/create_first_admin.py` exists solely to break that:
```bash
cd /opt/fim
venv/bin/python scripts/create_first_admin.py
```
Prompts for username/email/password interactively (password via `getpass`, never
echoed or left in shell history), validates the password against the same policy
`create_user` enforces, and refuses to run if an active admin already exists — so
it's safe to leave in place rather than needing deletion after first use. This
needs `DATABASE_URL` reachable (i.e. `.env` above already in place) but not the
backend actually running yet, since it talks to the DB directly rather than
through the API.

Do **not** use `scripts/create_test_users.py` for this — that one hardcodes weak
passwords (`admin123`, etc.) for four different roles and is dev/test-only.

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

~~⚠️ CORS origins are hardcoded in `app/main.py`~~ — fixed 2026-08-20, see §5:
set `CORS_ORIGINS` in `.env` instead (no source edit needed anymore).

**Optional: `fim-frontend-build.service`** (`etc/systemd/system/`) wraps the two
commands above (`npm install`/`npm run build` via `scripts/build-frontend.sh`) as
a `Type=oneshot` unit, so `systemctl start fim-frontend-build` rebuilds the
frontend without needing to `cd`/remember the flags. Not part of the flow above
(that's a plain manual build, which is all you need) — this is just a convenience
if you'd rather trigger a rebuild via `systemctl` than a shell one-liner:
```bash
sudo cp etc/systemd/system/fim-frontend-build.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl start fim-frontend-build   # rebuilds now
sudo systemctl status fim-frontend-build  # oneshot units show "inactive (dead)" once done — that's success, not failure
```

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

⚠️ **Where `server.api_key`'s value comes from — this isn't issued by the server
ahead of time.** `POST /api/v1/agents/register` (`app/api/agents.py`) is
trust-on-first-contact: for a hostname it's never seen, it accepts whatever
string is sent as the `X-API-Key` header and stores its hash as that agent's
credential from then on; only a *re-registration* of an already-known hostname
has to prove it holds the previously-established key. So the value you put in
`agent_config.yaml` isn't looked up or validated against anything server-side
the first time — you generate it yourself, and whatever you put there becomes
the real credential the moment this agent first registers:
```bash
openssl rand -hex 32   # use this as server.api_key below
```

```bash
scp agent/fim_agent.py agent/config/agent_config.yaml.example root@monitored-host:/opt/fim-agent/
ssh root@monitored-host
cd /opt/fim-agent
mv agent_config.yaml.example config/agent_config.yaml
vi config/agent_config.yaml
# Set: server.url (https://your-new-hostname), server.api_key (the openssl output above),
# agent.hostname, monitored_paths
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

Update 2026-08-20: this repo used to have **five overlapping backup script
variants**, the result of several separate "let's fix backups" attempts over time
without cleaning up the previous one. Three are now retired to `archive/scripts/`
(kept for history, `git log --follow` still works, not part of the active tree);
a fourth was never in git at all. `gap16_backup_encryption.sh` is the one kept
active — standardize on it for any new deployment.

| Script | Target dir | Auth | Encrypted? | Status found live |
|---|---|---|---|---|
| `archive/scripts/backup_fim.sh` (was repo root) | `/opt/fim/backup/fim` | hardcoded plaintext password (already rotated) | No | Ran once, produced a 20-byte broken dump, never scheduled |
| `archive/scripts/setup_backups.sh` (was `scripts/`) → generates a script into `/opt/fim/fim-backups/scripts/` | `/opt/fim/fim-backups/dumps` | `~/.pgpass` | No | Interactive (`read` prompt) — can't run unattended as written |
| *(the actual script found live at)* `/opt/fim/fim-backups/scripts/*.sh` — **never in this repo at all** | `/opt/fim/fim-backups/dumps` | hardcoded plaintext password | No | Untracked; unclear if ever scheduled; nothing to retire in git |
| `archive/scripts/backup-complete-fim-local.sh` (was `scripts/`) | `/backup/fim` | `.pgpass` (no hardcoded password — the best-practice one of the retired four) | No | Not verified scheduled |
| **`scripts/gap16_backup_encryption.sh`** (active) → generates `/usr/local/bin/fim-backup.sh` | `/opt/fim/fim-backups` | peer auth (`sudo -u postgres`, no password at all) | **Yes — GPG AES-256, verified decrypt roundtrip before deleting plaintext** | Ran once successfully in June, its cron entry (`/etc/cron.d/fim-backup`) had disappeared by August with no explanation found |

It's the only one that's actually encrypted, doesn't need a stored plaintext
credential, and self-verifies before deleting the unencrypted dump.

```bash
sudo bash scripts/gap16_backup_encryption.sh
```
This generates `/usr/local/bin/fim-backup.sh`, creates `/etc/fim/backup-passphrase`
(back this up off-server immediately — without it, encrypted backups are permanently
unrecoverable), and installs its own `/etc/cron.d/fim-backup` entry.

⚠️ **Before scheduling it, check real headroom, not just default settings.** The
script's default `KEEP_BACKUPS=7` assumes there's room for 7 copies of a compressed
full dump. On a database dominated by `fim.scans` (which can legitimately reach
double-digit GB — see the disk-full incident in `CHANGELOG.md`), this can exceed a
small volume's entire free space. A live test on a ~17GB database failed mid-run with
`gpg: ... write error: No space left on device`, leaving a corrupt partial `.gpg` file
and a full-size plaintext `.dump` both on disk simultaneously (worst case: the
script needs room for *both* at once, since the plaintext is only deleted after a
successful verified encrypt). Check `pg_database_size('fim_db')` and run one real
backup manually to see its actual compressed size before trusting any `KEEP_BACKUPS`
value, and confirm free space is comfortably more than `KEEP_BACKUPS × one backup's
size` before scheduling.

If this environment's convention is a `cronwrap`-style wrapper (check
`/usr/local/bin/cronwrap` — some deployments use this instead of a bare
`/etc/cron.d` entry for logging/failure-notification), remove the script's
self-installed `/etc/cron.d/fim-backup` and add the equivalent line to root's
personal crontab instead, e.g.:
```bash
rm -f /etc/cron.d/fim-backup
(crontab -l 2>/dev/null; echo '0 2 * * *  /usr/local/bin/cronwrap /usr/local/bin/fim-backup.sh "fim-backup" <alert-email>') | crontab -
```

Verify a manual run succeeds and actually restores:
```bash
sudo bash /usr/local/bin/fim-backup.sh
gpg --batch --passphrase-file /etc/fim/backup-passphrase \
    --decrypt /opt/fim/fim-backups/fim_backup_<timestamp>.dump.gpg \
    | pg_restore --list   # confirms the archive is real, doesn't touch the live DB
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
- [ ] Log in as an admin and check **System Health** (Administration → System
      Health) — confirm disk usage is reported and set the warning/critical
      thresholds to something sensible for this box's actual disk size, not the
      85%/92% defaults if this volume is small
- [ ] Confirm `scripts/fim-disk-cleanup.sh` and `scripts/cleanup_scan_data.sh` are
      both deployed to `/usr/local/bin/` *and* actually scheduled (`crontab -l` or
      `/etc/cron.d/`) — both were found written-but-never-scheduled on a real
      deployment; being present in `/usr/local/bin/` doesn't mean anything runs them

---

## Appendix: known gaps to fix upstream (not blockers, but worth doing)

- ~~No `000_initial_schema.sql`~~ — fixed 2026-08-20: `0000_initial_schema` +
  `0014_unmanaged_tables_dump` now create all 33/33 real tables from nothing (§4).
  A genuine from-scratch install no longer needs `pg_dump`/`pg_restore` at all.
- ~~`CORS_ORIGINS` dead code~~ — fixed 2026-08-20: `app/main.py` now reads
  `settings.cors_origins` instead of a hardcoded list. `config.py`'s default is
  the three localhost dev-server origins only — **production deployments must
  set `CORS_ORIGINS` in `.env`** (see `.env.example`) or the real frontend gets
  CORS errors. This is a real behavior change for any already-running instance
  that never had `CORS_ORIGINS` in its `.env`: check and set it *before*
  restarting the backend with this update, matching whatever's currently
  hardcoded for that instance.
- `SMTP_*` settings in `.env.example`/`config.py` are dead code for the same reason —
  either wire `email_service.py` to use them as an SMTP fallback, or remove them.
- ~~`SECRET_KEY`/`JWT_ALGORITHM`/`ACCESS_TOKEN_EXPIRE_MINUTES`/`REPORT_*` via
  `os.getenv()`~~ — fixed 2026-08-20, see §5.
- ~~Conflicting systemd unit templates~~ — fixed 2026-08-20, see §0 and §9.
  `etc/systemd/system/fim-agent.service` was also fixed to match the `/opt/fim-agent`
  convention that `agent-install.sh`/README/§12 already agreed on (it was the one
  outlier, using `/opt/fim/agent` + a stale venv path).
- ~~`fim-frontend-build.service` undocumented~~ — fixed 2026-08-20, see §7. It's an
  optional convenience wrapper around the manual build step, not a required step.
- ~~`gap21_baseline_version_control.sh` hardcodes `/opt/fim/baselines-git`~~ — fixed
  2026-08-20: both the script's own `BASELINES_GIT` variable and the
  `BASELINES_GIT_DIR` constant in the `baseline_version_control.py` service it
  generates now respect `FIM_HOME` (falling back to `/opt/fim` unchanged).
- ~~No first-admin-user creation step~~ — fixed 2026-08-20:
  `scripts/create_first_admin.py`, documented in §5.
- ~~Five overlapping backup script variants~~ — fixed 2026-08-20, see §13: three
  retired to `archive/scripts/`, one was never in git, `gap16_backup_encryption.sh`
  is the one active script now.
- `fim.scans` stores each scan's full file listing as JSONB (`scan_data`) with no
  hard upper bound beyond the 30-day-null / 3-month-delete retention in
  `cleanup_scan_data.sh` — for a very large monitored fleet this could still
  legitimately dominate `fim_db`'s size well before the 3-month cutoff. Worth
  monitoring via System Health rather than assuming the retention alone is enough.
