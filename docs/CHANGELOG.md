# Changelog

Real changes only — what actually happened and why, not a commit-message dump.
Dates below are grounded in migration filenames (`app/db/migrations/versions/`) and
direct observation; entries without a firm date are grouped by theme instead of guessed.

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
