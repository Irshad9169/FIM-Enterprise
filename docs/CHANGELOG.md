# Changelog

Real changes only — what actually happened and why, not a commit-message dump.
Dates below are grounded in migration filenames (`app/db/migrations/versions/`) and
direct observation; entries without a firm date are grouped by theme instead of guessed.

## 2026-08-20: Fresh-install/migration portability audit and fixes

User asked whether the project could migrate easily to a new server. A research
agent produced a bottleneck list with file:line evidence; each finding was fixed
one at a time, verified, and committed to `feature/upgrades`
(`21f8e6b`…`c7149f5`).

- **No from-scratch schema (the real blocker)**: `alembic upgrade head` against a
  genuinely empty database previously created almost nothing — migration `0001`
  was a no-op, and every real table was assumed to already exist. New migrations
  `0000_initial_schema` (24 tables — the 22 ORM-modeled ones, DDL generated
  mechanically from live SQLAlchemy metadata, plus 2 of the 11 "unmanaged"
  raw-SQL tables whose DDL already existed in-repo) and
  `0014_unmanaged_tables_dump` (the remaining 9, a real schema-only `pg_dump`
  from `fim_db` — not guessed, since two of those tables have real gotchas that
  guessing would've missed: `scans_archive` has no primary key at all in
  production, and `file_changes.scan_id` has no FK to `fim.scans` despite the
  name) now bootstrap all 33 tables + both tamper-evidence triggers from
  nothing. Verified end-to-end on test06 against a scratch `fim_fresh_test`
  database: 34 relations, `alembic_version` at head. One real bug caught during
  that validation: `env.py`'s new `CREATE SCHEMA` call needed its own explicit
  `connection.commit()` — without it, Alembic's own transaction wrapped the
  whole 14-migration batch as a nested savepoint instead of the real
  transaction, and it silently rolled back on connection close with every
  "Running upgrade" line still logging as if it had succeeded.
- **CORS origins were hardcoded** to test06's specific hostnames in
  `app/main.py`. Now reads `settings.cors_origins` (`CORS_ORIGINS` in `.env`,
  a field that existed but was never actually wired up). Zero-risk to deploy:
  test06's `.env` already had `CORS_ORIGINS` set to the exact values that were
  hardcoded, just never read.
- **`SECRET_KEY`/`ALGORITHM`/`ACCESS_TOKEN_EXPIRE_MINUTES`
  (`app/core/security.py`) and `REPORT_AUTO_GENERATE`/`REPORT_SCHEDULE_HOUR`/
  `REPORT_SCHEDULE_MINUTE` (`report_scheduler.py`) read via bare `os.getenv()`**
  with an insecure fallback (`SECRET_KEY` defaulted to the literal string
  `"your-secret-key-change-in-production"`) that kicked in silently if a
  systemd unit didn't load `.env` into real process environment — the same
  class of live auth-bypass risk already found and fixed operationally once
  before (2026-07-24, see below). Now both read from the validated `Settings`
  object, which fails loudly (`pydantic.ValidationError`) if `secret_key` is
  missing, and loads `.env` directly regardless of process environment. Also
  fixed a naming mismatch found in the process: `.env.example` always
  documented `ALGORITHM`, but the old code read `JWT_ALGORITHM` instead, so
  setting `ALGORITHM` never did anything.
- **Conflicting systemd unit templates**: `fim-backend.service` had a real bug
  (`WorkingDirectory=/opt/fim` but `ExecStart` pointed at a different
  `/usr/local/opt/fim` venv), ran as `root`, single worker, no
  `EnvironmentFile=`. Fixed to match what `PRODUCTION_DEPLOYMENT.md` already
  recommended. `fim-server.service` — a full duplicate under a different unit
  name, still referenced by a family of older scripts (`deploy-dashboard.sh`,
  `fix-cors.sh`, `verify-dashboard.sh`, `verify_phase1.sh`,
  `verify_phase2_deployment.sh`) that predate the `fim-backend` naming — was
  archived rather than left live. `fim-agent.service` was also fixed; it was
  the one file still using `/opt/fim/agent` while `agent-install.sh`, README,
  and the deployment guide's own agent section all already agreed on
  `/opt/fim-agent`.
- Smaller fixes closed the same day: `gap21_baseline_version_control.sh`
  hardcoded `/opt/fim/baselines-git` instead of respecting `FIM_HOME` (fixed in
  both the script and the `baseline_version_control.py` service it generates);
  no first-admin-user creation step existed for a genuine from-scratch install
  (added `scripts/create_first_admin.py` — interactive, password-policy
  enforced, refuses to run if an admin already exists); three of five
  overlapping backup script variants (`backup_fim.sh`, `setup_backups.sh`,
  `backup-complete-fim-local.sh`) retired to `archive/scripts/`, leaving
  `gap16_backup_encryption.sh` as the one active script; `fim-frontend-build.service`
  was undocumented (not dead — documented instead of removed).
- Explicitly declined/deferred, not fixed: RT ticket URL hardcoded in 5
  frontend files (user: not needed unless targeting a different org); real
  secrets checked into git — `agent/config/agent_config.yaml` and
  `master_configs/test06.hyd.int.untd.com.yaml` (user: "leave it and record
  it" — joins the existing token.json rotation queue).

## 2026-08-17: Bulk-select and bulk-submit for Daily Report agents

Analysts previously had to click Submit on each agent individually within a
report, even when several hosts shared the same RT ticket. Added per-row
checkboxes (both classic and grouped report views), a "select all pending"
toggle, and a bulk-submit modal that keeps each agent's own RT#/note
independently editable (pre-filled from whatever's already correlated) and
submits them all in one pass via the existing per-hostname submit endpoint —
no backend change needed.

## 2026-08-14: Postgres log growth from `log_statement = 'mod'`, unrelated to the two disk-full incidents below

A day after the `log_duration = 'on'` incident (2026-08-13) was fixed, Postgres's
log directory started growing again — `postgresql-Fri.log` reached 1.1GB within
hours. Different root cause this time: `log_statement = 'mod'` logs the full text
of every INSERT/UPDATE/DELETE/DDL statement (not just slow ones), and
`log_parameter_max_length = -1` meant each logged statement's parameters were
dumped with no length cap — `threatos`'s high-frequency writes with full JSONB
payloads were the dominant contributor, same shared-instance pattern as the prior
incident. A second, independent bug compounded it: `log_filename =
'postgresql-%a.log'` names files by weekday only, so when `log_rotation_size`
(100MB) tried to trigger mid-day, Postgres couldn't produce a new filename and
just kept appending to the same file — the size cap silently never took effect
within a day.

Fixed via `ALTER SYSTEM` (reload only, no restart): `log_statement = 'none'`
(errors and slow queries ≥5s still logged via `log_min_duration_statement`,
which was fine and not the problem), `log_parameter_max_length = 512` (truncates
rather than dumping full payloads even for logged slow queries), and
`log_filename = 'postgresql-%Y-%m-%d_%H%M%S.log'` (timestamped, so every
rotation gets a distinct file and the size cap actually works), followed by
`pg_rotate_logfile()` to apply immediately. Added `/usr/local/bin/pg-log-cleanup.sh`
(gzips logs older than 2 days, deletes gzipped ones older than 30) scheduled via
the same `cronwrap` convention as `fim-disk-cleanup.sh`. Confirmed fixed:
daily logs dropped to 54K–110K/day, down from 900MB–4.5GB/day.

## 2026-08-13: Second disk-full incident — different root cause this time

Disk hit 0 bytes free again, two days after the incident below was believed fixed.
This time `/opt` and `pg_wal` were both healthy — the growth was entirely inside
`/var/lib/pgsql/15/data` (37GB, up from ~27GB two days prior), and the fixes from
2026-08-10/11 (VACUUM, autovacuum tuning, extended retention) were not the cause of
the recurrence. No disk resize was available this time, forcing a more careful
investigation instead of repeating the same fix.

- **Actual root cause: `/var/lib/pgsql/15/data/log/` had grown to ~19GB** across a
  week of daily log files (5.4G, 5.2G, 4.2G on the three biggest days alone) — not
  database data, but Postgres's own text logs. `log_duration = 'on'` (set via
  `ALTER SYSTEM`, so it lived in `postgresql.auto.conf`, not `postgresql.conf` —
  easy to miss) logs a `duration: X ms` line for **every single statement**,
  bypassing `log_min_duration_statement`'s 5s threshold entirely. Confirmed live:
  a freshly-truncated log file regrew to 1.2GB within roughly a minute. Traced the
  bulk of the volume to `threatos` — an unrelated application sharing this same
  Postgres instance — running a very high-frequency, low-latency query workload,
  with every query individually logged.
- Fixed by `ALTER SYSTEM SET log_duration = 'off'` + `pg_reload_conf()` (no restart
  needed). Confirmed via a 30-second flat-size check post-fix. Left
  `log_statement = 'mod'` alone — that's a reasonable audit-logging choice and
  wasn't the problem.
- ⚠️ This setting is **instance-wide**, not per-database — the fix affects
  `threatos`'s logging too, not just `fim_db`'s. It looked like a forgotten debug
  flag rather than a deliberate choice (logging every sub-millisecond query
  indefinitely isn't a normal production setting for anyone), but worth a heads-up
  to whoever owns `threatos` if this instance is meant to be shared long-term.
- Immediate recovery: deleted the old, clearly-inactive rotated day-of-week log
  files (`postgresql-Mon.log` etc. — plain `rm -f`, nothing had them open) and
  truncated (not deleted) the currently-open file in place (`: > postgresql-Thu.log`)
  so space was reclaimed immediately without needing to wait for a process to
  release a file handle — same "space isn't freed until every open handle closes"
  lesson from the first incident, applied correctly this time without needing to
  hunt for what was holding a handle.
- **Takeaway for future incidents**: check `/var/lib/pgsql/<ver>/data/log/` size
  *before* assuming a repeat is the same root cause as last time. This instance's
  own logs, not `fim.scans`, were the dominant contributor on this occasion.
- Confirmed after the fact: `fim_db` was still exactly 17GB, unchanged from
  2026-08-11 — the 2026-08-10/11 `fim.scans` retention fix is holding correctly.
  Its row count actually grew (2,733 → 4,874 over the same two days) while total
  size stayed flat, meaning old rows are being pruned at roughly the rate new ones
  arrive. That fix was not the cause of this recurrence.

## 2026-08-10 — 2026-08-11: Disk-full incident, System Health page, backup review

- **Root-caused and fixed a full production-adjacent outage**: `fim.scans` grew to
  ~27GB of mostly-dead TOAST storage and took `/dev/vda2` to 0 bytes free, crashing
  Postgres mid-write. Two compounding causes: `scripts/cleanup_scan_data.sh` nulled
  old `scan_data` JSONB values but never ran `VACUUM` afterward (so nothing was ever
  reclaimed), and `fim.scans`' autovacuum never triggered on its own because the
  default thresholds are based on row counts, not TOAST size. Fixed both: the script
  now runs `VACUUM` after its `UPDATE`, and migration `0011_scans_autovacuum_tuning`
  sets an aggressive per-table autovacuum threshold as a safety net independent of
  the script. `fim.scans` also now fully deletes rows past 3 months, not just nulls
  the payload at 30 days.
- Recovery required a disk resize (40G → 49G) — VACUUM/DELETE/UPDATE all need
  temporary headroom, which a fully-0%-free disk doesn't have; this is why the
  incident needed more than a query to fix.
- Added **System Health** page (Administration, admin-only): live disk usage and
  top Postgres table sizes (`app/api/system.py`, `GET /api/v1/system/disk-health`),
  with a pulsing sidebar badge visible from any page — the ambient signal that
  would have caught this before it became an outage.
- Made the warning/critical disk thresholds **admin-configurable** (sliders on the
  System Health page) instead of hardcoded — `fim.system_settings` (migration
  `0012_system_settings`), `GET`/`PUT /api/v1/system/settings`. `fim-disk-cleanup.sh`
  now reads these same thresholds from the DB (falls back to 85/92 if unreachable),
  so the UI sliders actually change the script's behavior, not just the dashboard.
- Discovered `fim-disk-cleanup.sh` and `cleanup_scan_data.sh` were both written but
  **never actually scheduled** (no crontab, no `/etc/cron.d` entry) — deployed to
  `/usr/local/bin/` back in May but inert since. Scheduled properly via root's
  personal crontab using this environment's `cronwrap` convention.
- Reviewed the backup story and found **three separate, mostly-broken backup
  mechanisms**: `backup_fim.sh` (repo root) and an untracked script in
  `/opt/fim/fim-backups/scripts/` both have a hardcoded plaintext DB password and
  neither ever produced a real backup; `gap16_backup_encryption.sh`'s generated
  mechanism (`/usr/local/bin/fim-backup.sh`, peer-auth `pg_dump`, GPG-AES256,
  verified restore roundtrip) is the sound one, but its cron entry had silently
  disappeared since its one successful run in June. Re-verified the mechanism
  works; **deliberately did not reschedule it yet** — its default `KEEP_BACKUPS=7`
  could recreate the same disk-full scenario on this box's current headroom. See
  `docs/PRODUCTION_DEPLOYMENT.md` before scheduling it for real.
- Fixed `fim.alerts`/`fim.report_changes`/`fim.scans` ownership gaps found along the
  way (several were owned by `postgres`, not `fim_app`, blocking `ALTER TABLE` from
  the app's own migration user).

## 2026-08-06: Report + alert display fixes

- `GET /api/v1/alerts` never joined `Agent.hostname` — the Alerts page's Agent
  column was always blank. Fixed with a join in `app/api/alerts.py`.
- Daily report generation (`report_scheduler.py` and the manual `/reports/generate`
  endpoint) pulled every alert for the date with **no status filter** — so alerts
  already marked `false_positive` still showed up in reports generated after the
  fact. Both now exclude `false_positive` at generation time.
- Fixed the Classic report change-list view (`ReportDetailPage.tsx`'s `ChangeRow`)
  showing only path + hash, no mtime and no visual Added/Removed/Changed
  distinction — it was using an older, simpler renderer than `GroupedChangesView`.
  Now shares the same color-coded change-type labels and Mtime line.

## 2026-08-05: Agent-side generational upgrade + self-triggering loop fixes

The agent gained, in roughly this order: `exclude_patterns` support (previously
silently ignored — a real, live bug meaning nothing configured in
`agent_config.yaml` actually excluded anything), incremental scan caching
(mtime+size-based skip, persisted correctly across restarts), real-time filesystem
watching via `watchdog` (debounced, falls back to scheduled-only if not installed),
content diffing for config-shaped files (size-capped at 2MB to avoid unbounded
shadow-copy growth), chunked scan submission (avoids 413s on large monitored
trees), remote config push (edit monitored paths from the UI, applied live on next
heartbeat), scan pause/resume, and agent self-integrity hash reporting.

Also fixed, found live via production-adjacent hosts still running an older agent
generation:
- **Alerts re-firing forever** for both modified/created and deleted files —
  `ChangeDetector` always diffs against the approved baseline, never the previous
  scan, so an unapproved baseline meant every subsequent scan re-detected the same
  diff as a "new" alert. Fixed by deduping against *any* prior alert for the same
  file+hash fingerprint (or, for deletions, whether the most recent alert for that
  path was already a deletion), regardless of that alert's status — not just
  currently-open ones. This scales to any number of hosts with zero manual
  per-host re-baselining.
- **Two self-triggering rescan loops**: the content-shadow directory and the
  incremental-scan cache file (including its `.tmp` atomic-rename intermediate)
  weren't excluded from the real-time watcher, so the agent's own bookkeeping
  writes looked like real file changes, triggering another scan, which did the
  same writes again — indefinitely. Found live via a scan restarting within
  seconds of the last one finishing, then later via a subtler ~20-minute-cadence
  version once the first two causes were fixed.
- A stale in-memory cache bug (`FileScanner._prev_cache` loaded once at process
  start, never refreshed) meant a long-running agent process compared every scan
  after the first against an increasingly stale snapshot instead of the previous
  scan — silently defeating incremental caching's whole point for the normal
  (no-restart) operating mode.
- Content-shadow disk growth was uncapped — a single large "config-shaped" file
  under a monitored path (not just small `/etc` configs) could balloon shadow-copy
  storage with no limit. Capped at 2MB per file.

## 2026-07-29 — 2026-07-30: Security fixes, agent protocol features

- **Live JWT auth-bypass fixed**: `SECRET_KEY` (and several other settings) were
  read via `os.getenv()` directly, bypassing the pydantic `Settings` class that
  actually loads `.env` — unless `.env` was also loaded as real process environment
  variables (`EnvironmentFile=` in the systemd unit), `SECRET_KEY` silently fell
  back to a hardcoded literal string. Fixed on both instances via `EnvironmentFile=`.
- **Real per-agent API key authentication** (`app/core/agent_auth.py`) replaced an
  HMAC-signature scheme that only verified a signature against the same request's
  own `X-API-Key` — a self-consistency check, not real authentication (any caller
  could invent a key and sign with it).
- `GET /api/v1/scans` and `GET /api/v1/scans/{scan_id}` had **no authentication at
  all** — unlike every comparable read endpoint. Anyone could walk the whole
  fleet's file inventory and config content diffs with no credentials. Fixed.
- Timezone bug in scan submission: the agent sends a naive (no-offset) UTC
  timestamp; the server's `.astimezone(timezone.utc)` on a naive datetime assumes
  it's already in the *server's local* timezone, silently mis-shifting an
  already-UTC value. Fixed by attaching `tzinfo=timezone.utc` before converting.
- Alert hash-chain / tamper-evident `fim.alerts` (`protect_alert_evidence` DB
  trigger, migration `0002_alert_hash_chain`) — blocks `DELETE` entirely, even for
  a superuser; only evidence-bearing columns are protected, `status`/
  `resolution_notes`/etc remain updatable so the review workflow still works.
- Auditd correlation, agent binary/self-integrity hash tracking, agent config-push
  protocol (`desired_config`/`reported_config`/version-ack), and content-diff
  columns on `fim.report_changes` all landed as part of this same stretch
  (migrations `0003`–`0009`).
- Anomaly detection engine (`app/services/anomaly_detector.py`, GAP #19) was
  completely non-functional despite reporting success — its agent-selection query
  referenced a column (`last_seen`) that doesn't exist and a status value
  (`'active'`) that isn't legal per the table's own CHECK constraint, so it threw
  on every run, silently swallowed by its own outer `except`. Fixed.
- `require_role(list)` bug found in `app/core/rbac.py` — passing a list where a
  string is compared collapses to admin-only (a string is never `==` a list in
  Python). Confirmed dead code today: only reachable from `agents_enhanced`/
  `scan_requests`, neither of which is mounted in `app/main.py`. **Not yet fixed** —
  low priority while those routers stay unmounted.

## Earlier (undated in this changelog, see git log for specifics)

- ~65 unit tests + integration tests against a real Postgres instance, CI-green.
  Integration testing surfaced and fixed a real DB connection leak and a baseline
  RBAC gap.
- Dependency hygiene pass: targeted CVE fixes (not a blanket FastAPI/Starlette
  version bump), `ruff` added to CI.
- `FIM_HOME` environment variable introduced so a second instance can run from a
  different install path without sharing production's config/baselines/frontend —
  six previously-hardcoded `/opt/fim` references now resolve through it.

## Known dead code (written, never wired in — not a bug, just untracked scope)

- `app/api/mfa.py` / `app/core/mfa.py` / `frontend/src/pages/MFASettingsPage.tsx` —
  MFA is implemented but the router isn't mounted and the page isn't routed.
- `app/api/agents_enhanced.py`, `app/api/scan_requests.py` — not mounted in
  `app/main.py`; this is also why `require_role(list)`'s bug above hasn't mattered.
- `app/services/scan_signing.py` — HMAC scan-signature verification, superseded by
  real per-agent key auth (see 2026-07-29 entry) but never removed; nothing calls it.
- `app/services/report_generator.py` — an older report-generation path with its own
  `correlation_groups` table writes; the actual scheduler (`report_scheduler.py`)
  and `/reports/generate` endpoint use different, newer logic entirely.
