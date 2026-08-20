# Archive

Files and folders moved out of the active tree during the 2026-07-24 cleanup.
Nothing here is imported, built, deployed, or referenced by any active code path —
each item was verified via grep/tsconfig/systemd-unit checks before moving. Moved
with `git mv` so full history is preserved (`git log --follow <path>`).

Safe to delete entirely once no longer needed for reference.

## Contents

- `app/`, `agent/`, `go-agent/` — superseded backup files (`.backup-spa`, `.phase0`,
  `.original`, `.before_alert_fix`, `-before-SSO-MFA`, `.WORKING_BKP`), one-off patch
  scripts (`fix_heartbeat.py`, `fix_register.py`) already applied to `agent/fim_agent.py`,
  a misplaced test file (`agents_enhanced_test.py`), a non-compiling Go file
  (`main.go.broken`), and an old agent config tarball.
- `frontend-nextjs-attempt/` — an abandoned parallel Next.js rewrite (`app/` route
  groups, top-level `components/`, `lib/`, `hooks/`, `next.config.mjs`, `next-env.d.ts`).
  The active frontend is `frontend/src/` (Vite + React Router); `frontend/package.json`
  has no `next` dependency and `frontend/tsconfig.json` only includes `src`.
- `frontend-misc/` — stray `tree`-command output dumps (`*.txt`), accidental empty
  files (`ls`, `npm`, `tsc`, `bTime`), a source tarball snapshot, and a stray `.new` file.
- `scripts/` — a superseded `.sh-bak` script, plus (2026-08-20) three of the five
  overlapping backup script variants documented in `docs/PRODUCTION_DEPLOYMENT.md`
  §13: `backup_fim.sh` (hardcoded plaintext DB password — already rotated by the
  user directly, per [[project-pending-security-cleanup]]/prior session), which
  used to live at repo root; `setup_backups.sh` (interactive `read` prompt, can't
  run unattended, references a nonexistent `fim-server` service); and
  `backup-complete-fim-local.sh` (`.pgpass`-based, no hardcoded password — the
  best of the four retired ones, but still superseded). `gap16_backup_encryption.sh`
  is the one kept active — real GPG encryption, peer-auth (no stored password at
  all), verified decrypt roundtrip before deleting the plaintext dump. A fourth
  variant (an untracked script at `/opt/fim/fim-backups/scripts/*.sh` on a real
  deployment) was never in git at all — nothing to archive there, just don't
  copy it to a new server.
- `backups/` — the former root-level `backups/` folder, consolidated here.
- `root/` — old README, a stray `tree` dump, a sample generated report, and an
  unused root-level `package.json`/`package-lock.json` (the real frontend deps live
  in `frontend/package.json`; all build scripts `cd frontend` before running npm).
- `etc-fim-server.service` — 2026-08-20: a full duplicate of
  `etc/systemd/system/fim-backend.service` under a different unit name
  (`fim-server`), with `secauto`/4-workers/no-`EnvironmentFile=` vs the other's
  `root`/1-worker at the time. `fim-backend` is the name actually running in
  production (`fim-backend`/`fim-backend-test`, confirmed live all session);
  `fim-backend.service` now has the corrected content (matches
  `docs/PRODUCTION_DEPLOYMENT.md` §9: `secauto`, 4 workers, `EnvironmentFile=`).
  **Not fully dead**, though: `scripts/deploy-dashboard.sh`, `fix-cors.sh`,
  `verify-dashboard.sh`, `verify_phase1.sh`, and `verify_phase2_deployment.sh`
  all still hardcode `systemctl ... fim-server` — those scripts predate the
  `fim-backend` naming and will silently no-op (`is-active` on a nonexistent
  unit) against any real `fim-backend`-named deployment. Not rewritten as part
  of this cleanup; treat any of those scripts' output as unreliable until they
  are.

## Deliberately NOT archived

- `app/api/token.json` — contains a live JWT. Recommend rotating the signing secret
  and deleting the file rather than archiving it (archiving doesn't remove it from
  git history).
- `go-agent/fim-agent-go` — a committed compiled binary; kept as-is since it's a
  deploy artifact, not dead code.
- `load_test.py` (root) — an active dev/test tool.
