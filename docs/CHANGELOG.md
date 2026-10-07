# Changelog

Real changes only — what actually happened and why, not a commit-message dump.
Dates below are grounded in migration filenames (`app/db/migrations/versions/`) and
direct observation; entries without a firm date are grouped by theme instead of guessed.

## 2026-10-07: SQL injection in bulk alert actions, fleet agent migration

- **`PATCH /api/v1/alerts/bulk` built its `WHERE id IN (...)` clause by
  f-string-interpolating the raw `alert_ids` list straight into a `text()`
  SQL string** (`",".join(f"'{aid}'" for aid in req.alert_ids)`), with no
  validation that each id was even a UUID. Flagged during an unrelated
  file-upload security review. Fixed by dropping the raw SQL entirely in
  favor of a parameterized `sqlalchemy.update(Alert).where(Alert.id.in_(...))`
  construct, after first parsing every id with `uuid.UUID(...)` and
  returning a clean 400 on anything that isn't one (previously any
  malformed id would have reached the database as part of the query text).
  Covered by `test_bulk_alert_action_rejects_non_uuid_id` and
  `test_bulk_alert_action_acknowledges_only_open_matching_alerts` in
  `tests/integration/test_api_flows.py`.
- **test04 and test05 migrated to test02's agent code/config**, reporting to
  the `feature/upgrades` backend (`test06:8803`) instead of the stale `main`
  backend (`test06:8000`) they'd been pointed at. Both reused their existing
  server-side agent identity via hostname-keyed registration and
  trust-on-first-contact API key bootstrapping — no data loss, no new
  agent records. This was also the real root cause of a separate
  "alerts keep repeating" report: `main`'s dedup logic only checks for a
  currently-*open* duplicate, so acknowledging/resolving an alert always let
  the next scan re-fire it; `feature/upgrades` fixed that months ago but the
  fix never reached these two hosts because their agents were talking to the
  wrong backend port the whole time.

**Deployed:** pulled to `/opt/FIM-PROJ/FIM-Enterprise` on test06 (commit `b903430`,
fast-forward, clean) and `fim-backend-test.service` (port 8803) restarted the same day;
confirmed clean startup with no errors and agent heartbeats (test02/test04/test05) flowing
immediately after.

## 2026-10-07: Correlate All — one dropped DB connection took down the whole run

User: "Correlate All is taking time and I get API error." Live logs
(`fim-backend-test`, test06) showed the real sequence: `search_rt_by_hostname` for
`test04.hyd.int.untd.com` failed with `asyncpg.exceptions.InterfaceError: connection is
closed`, then every host processed after it (`test02`, `test05`) immediately failed too with
`PendingRollbackError: Can't reconnect until invalid transaction is rolled back`, and the
final `db.commit()` failed the same way — surfacing to the browser as a plain 500.

Two compounding bugs in `correlate_all_agents` (`app/services/ticket_linker.py`):

1. The entire per-host loop ran inside **one transaction, committed only once at the very
   end**, while making slow sequential external calls (Phantom CMR match, RT search, JIRA
   search) for every host in between DB writes. Confirmed live:
   `idle_in_transaction_session_timeout` on this Postgres instance is 5 minutes — easily
   exceeded on a multi-host report given the CMR fetch alone can take ~1.5 minutes
   (see [[project_cmr_auto_login_built]]'s concurrency-throttle trade-off). Postgres silently
   killed the idle transaction's connection mid-run.
2. The per-host `except Exception` handler logged the error and moved on, but never called
   `db.rollback()`. Once one DB error invalidates a SQLAlchemy session's transaction, every
   later query on that same session raises `PendingRollbackError` until it's rolled back —
   so one transient connection drop cascaded into every subsequent host failing too, and the
   final summary UPDATE + commit failing last, which is what the frontend actually saw as
   "Internal Server Error."

Fixed: commit after each host instead of once at the end (keeps the transaction short-lived,
avoids the idle timeout entirely), and roll back the session in the except block before
continuing to the next host (so a single transient failure stays contained to that one host
instead of cascading). New regression test
`test_correlate_all_agents_rolls_back_and_continues_after_one_host_db_error` in
`tests/test_ticket_linker.py` simulates one host's DB call failing and asserts the other
hosts still process normally and `db.rollback()` was called exactly once.

**How to apply:** any long-running per-item loop that interleaves slow external I/O with DB
writes on the same session should commit frequently (keep transactions short) and roll back
on a per-item basis in its exception handler — never assume a caught exception leaves the
session usable for the next iteration.

## 2026-10-05: CMR session staleness masked by a surviving SSO cookie; reports list had no bound at all

Two independent live-debugging rounds with the user, same day.

- **CMR widget silently went empty again, no errors anywhere.** The Phantom
  session cookie (`phantom_sessionid`) had expired over a week earlier and
  was correctly filtered out by `_load_cmr_cookies()`'s manual expiry check
  — but `sso_auth` is deliberately written with `expires=0` (that cookie's
  own "no fixed expiry" convention, needed since the original SSO/Phantom
  handoff work) and is never filtered, so the cookie dict stayed non-empty.
  `has_valid_cmr_session()` only ever checked `bool(cookies)`, so it
  reported the stale session as valid, Correlate All skipped the re-login
  prompt, and the resulting Phantom request came back 200 OK with no real
  data and no recognizable SSO-login-page redirect either — a completely
  silent failure, no log trace at all. Fixed: both `has_valid_cmr_session()`
  and `fetch_recent_implemented_cmrs()` now specifically require
  `phantom_sessionid` in the loaded cookie dict, not just any cookie, and
  the latter logs clearly when it bails for this reason.
- **Confirming that fix surfaced a second issue: the widget took ~90
  seconds to load.** Direct cost of the concurrency throttle added
  2026-09-23 (below) — correctness over speed was the explicit trade-off
  made there. Since the realistic repeat cost is the same analyst
  reloading the Reports page within a few minutes rather than the first
  cold load, added a 180-second in-process cache
  (`TicketLinkerService._cmr_cache`, keyed by `days_back`) for successful
  results (including a legitimate empty list) without touching the
  concurrency throttle itself. A missing/expired session is deliberately
  never cached, so a fresh CMR login takes effect immediately rather than
  being masked for up to 180s.
- **Separately, `GET /api/v1/reports` had no limit or date filtering at
  all** — the frontend already sent `?limit=50`, but FastAPI silently
  ignores unrecognized query params, so every report row ever created was
  always returned and rendered. This is a daily-report system (one new row
  per day, indefinitely), so that's unbounded growth with no cap. Now
  defaults to the last 60 days when no range is given, accepts explicit
  `start_date`/`end_date` to reach further back, and caps `limit` at 200.
  Frontend got a small "Older reports: [from] to [to] [Clear]" filter row.

## 2026-09-18 — 2026-09-23: CMR (Phantom) on-demand login built, debugged live end-to-end, then two post-ship bugs fixed

The long-standing assumption was "Phantom has no service-account/API option,
only interactive SSO, so CMR fetching is stuck relying on an
externally-maintained cookie file." The real Boris source
(`authenticate.cgi`, `SSOAuth.pm`, `get_RT_CMRs`) reframed this: Boris uses
no service account either — a real person's raw username+password against
`auth.int.untd.com`'s `type=login` mode (distinct from the interactive
browser-redirect SSO used elsewhere), success detected by string-matching
`"Success. Loading..."`, then one visit to Phantom's front door to receive a
Phantom-specific session cookie. That's genuinely scriptable.

- Built `app/services/cmr_session_manager.py`: on-demand, prompted only when
  Correlate All has no valid session, never stores the credential. Rejected
  an initial scheduled/stored-credential design after direct pushback
  ("Boris doesn't use a service account... why are you making things
  harder?") — the mechanism never required one, only the first draft's
  comments overstated it.
- **Live debugging, fully root-caused via real diagnostics at each step:**
  SSO silently hangs (no response, no error) given FIM's own `origin_id` —
  switched to the legacy collector's known-working origin
  (`USTickets`/`US Tickets System`). The identical request then hung via
  `httpx` but succeeded in ~1s via real `curl` even after matching
  User-Agent — consistent with TLS client fingerprinting — switched to
  shelling out to real `curl` for both SSO hops. The cookie jar then only
  ever gained `sso_auth`, never a Phantom session cookie, because `curl`
  was never passed `-L`; added it. A live Phantom-side 504 at the very last
  redirect hop (reproduced via curl AND a real browser) confirmed the
  handshake itself was correct and the failure was external.
- **`correlate_all_agents` was calling Phantom `N × (1 + 3M)` times per
  click** (once per host, each call independently re-fetching and
  re-processing the entire CMR list) — found directly from the user's own
  hypothesis ("Phantom should be fetched for CMRs only once"). Split out a
  pure `_match_cmrs_to_hostname()` and made the fetch happen once per run.
  This likely explains some of the earlier "Phantom outage" symptom too.
- **Owner/Status/Start Time rendered as empty badges once CMRs finally
  appeared.** A real Phantom page packs several "Label: value" pairs onto
  one rendered text block with no separator (`"Status: Implemented Owner:
  'Alan Finney' ImplementorOwner: ..."`), so the original
  `line.startswith("Owner:")`-style checks never matched, and the guessed
  `"Implementation Start"` label never appears at all (the real one is
  `"Start Time:"`). Replaced with `_extract_field()`, a regex extractor
  that searches the full text and stops at the next known label — verified
  against real captured page text.
- **Fixing that then made it look like nothing improved**, because
  `fetch_recent_implemented_cmrs` fired `_fetch_cmr_detail` for every
  recent CMR at once via `asyncio.gather` — with ~30 CMRs, each opening its
  own client for 3 sequential requests, that's up to 90 near-simultaneous
  requests under one session cookie. Every single one timed out together,
  twice, in the same second, before ever reaching the just-fixed parsing
  code. Throttled via a semaphore (`CMR_DETAIL_CONCURRENCY = 3`) — the
  same class of "too much concurrent traffic against one session" problem
  as the per-host over-fetch above, just surfacing in the per-CMR fan-out
  instead. This also retroactively supports the earlier "Phantom outage"
  having been self-inflicted traffic all along, not an unrelated event.

## 2026-09-29: File-upload security review — hardened the one upload endpoint, removed a dead unsafe SPA handler

Prompted by an internal threat-intel note describing an incident elsewhere: an
app with unrestricted file uploads let an attacker land a web shell and
harvest credentials. Audited this codebase for the same exposure (allow-
listing, content-type/magic-byte validation, storage location, filename
randomization, AV scanning).

- **`POST /api/v1/exclusions/import`** (`app/api/exclusions.py`) is the only
  file-upload endpoint anywhere in the app. It never wrote the uploaded bytes
  to disk — the file is read into memory, decoded as text, and parsed
  line-by-line straight into `fim.whitelist_rules` rows — so the specific
  "uploaded file becomes web-reachable" scenario from the incident doesn't
  apply here; there's no file object ever created on the filesystem. It did
  have real gaps though: no allow-list on extension/content-type, no size
  cap, and an unhandled `UnicodeDecodeError` (a bare 500) on any non-UTF-8
  upload. Added `validate_import_upload()` — extension allow-list (`.txt` or
  extensionless), content-type allow-list (`text/plain` /
  `application/octet-stream` / unset), a 2 MB size cap, and a null-byte check
  as a binary-content guard — plus a clean 400 instead of a crash on bad
  encoding. The accepted file format is unchanged (matches `/export`'s own
  output: blank lines, `#` comments, glob `*` patterns, `regex:` prefix).
  Covered by `tests/test_exclusions_import.py`.
- **`app/api/frontend.py`** (an unwired, dead `serve_frontend` SPA handler)
  built `os.path.join(WEB_DIR, full_path)` straight from the raw URL path
  with no traversal sanitization — a real path-traversal *read* risk if it
  were ever mounted. It was leftover boilerplate (its own docstring says
  "Next.js"; this project is Vite/React) superseded by `app/main.py`'s
  already-active `SPAStaticFiles` mount, which subclasses Starlette's real
  `StaticFiles` and gets its built-in traversal protection for free. Deleted
  rather than fixed-and-kept — there's no future scenario where the older,
  less-safe SPA handler would be preferable to the one already mounted; a
  future frontend-serving change belongs in the existing `main.py` mount.
- No other upload/write surfaces found: no file-upload UI anywhere in the
  frontend, `/api/v1/scans/submit` takes structured JSON (size/count capped)
  not raw file bytes, baseline snapshots use server-generated filenames
  (timestamp + UUID, sanitized hostname) and live outside any web-served
  directory, and the host agent only ever writes to its own local,
  agent-controlled paths.

## 2026-09-09: Light theme actually themes the whole app, RT correlation "reject" bug, publish preview

- **Light/dark toggle only ever re-themed the sidebar/header.** Root cause was
  two-layered. First, `frontend/tailwind.config.cjs` was a stray, empty leftover
  config silently shadowing the real `tailwind.config.ts` (Tailwind's config
  resolution checks `.cjs` before `.ts`), so `darkMode: ["class"]` and the
  CSS-variable color-token system already written into the `.ts` config had
  never once actually loaded — dead scaffolding from an abandoned shadcn/ui
  setup (`components.json` still points at an `app/globals.css` that doesn't
  exist in this repo). Deleted the shadow config; its only consumer besides the
  dead one, a `tailwindcss-animate` plugin dependency that was never installed
  and nothing in the app uses (no Radix accordion anywhere), was removed too
  rather than adding a new dependency to unblock scaffolding nothing needs.
  Second, even once the token system could load, every page hardcoded
  dark-only classes (`bg-slate-900`, `text-white`, `border-slate-800`, ...)
  instead of theme tokens — only `DashboardLayout.tsx` ever consumed
  `ThemeContext`. Defined the missing light/dark CSS variables
  (`src/index.css`) and migrated all pages + shared components to
  `bg-background`/`bg-card`/`bg-muted`/`bg-secondary`/`text-foreground`/
  `text-muted-foreground`/`border-border`/`border-input`/`divide-border`.
  Finally, severity/status badge colors (alert severity, report/agent status
  chips) used dark-mode-tuned translucent backgrounds (e.g. `bg-red-900/20`)
  that read as a near-invisible tint against a light page — added light
  defaults (`bg-{hue}-50`/`border-{hue}-200`/`text-{hue}-700`, or a solid
  `bg-{hue}-600 text-white` for the two near-opaque toast banners) alongside
  `dark:` variants carrying the original dark-mode values unchanged.
- **RT correlation couldn't be rejected** — an analyst clearing an
  auto-correlated RT ticket back to blank (because it was the wrong match)
  would see it silently reappear at Submit, Bulk Submit, and in the final
  published report. Three compounding `|| fallback`/truthy-check bugs, all
  the same root cause: an explicit empty string (deliberately-rejected) and
  `None`/never-set were treated as identical, so the auto-match kept winning.
  Fixed in `EditAgentModal`/`SubmitAgentModal`/`BulkSubmitModal`
  (`ReportDetailPage.tsx`), `submit_agent` and the publish-content builder
  (`app/api/reports.py`, `app/services/ticket_linker.py`).
- **Report preview before publishing to RT**: `GET /{report_id}/publish-preview`
  (new) and `TicketLinkerService.preview_publish_content()` build the exact
  ticket match + comment text `publish_report()` would send, without sending
  it — surfaced in `PublishModal` as a full-screen panel (not a small dialog)
  so the exact content is actually readable before the irreversible publish.
- Recent RT tickets + implemented CMRs widget added to the Reports page
  (`GET /recent-activity`); CMR fetching is real but not yet functional in
  practice — Phantom has no service-account auth, only interactive SSO, and
  the one candidate cookie-jar file lives on a prod server unreachable from
  the test06 instance. RT tickets work today; CMRs are wired for whenever a
  real credential path exists.
- `SSO_SERVER_URL` switched from the QA endpoint (hardcoded) to production,
  and made a real setting (`app/core/config.py`, `app/core/sso_manager.py`).
- Session and audit-log timestamps were displaying as unconverted UTC
  (naive datetimes serialize without an offset, so the browser misread the
  raw clock numbers as local time). Fixed for Sessions/Audit pages via
  `app/core/time_utils.py`'s `as_utc()` and `frontend/src/lib/formatDate.ts`
  (explicit IST formatting, matching this project's existing convention).
  Same bug still present on nine other pages — deferred.
- `fim.scans` TOAST growth (not dead-tuple bloat) was outrunning
  `cleanup_scan_data.sh`'s daily `LIMIT 100` batch; increased run frequency
  (same proven-safe batch size, run 4x/day instead of once) rather than the
  batch size, to avoid the WAL-exhaustion crash risk from the disk-full
  incidents below.

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
