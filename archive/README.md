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
- `scripts/` — a superseded `.sh-bak` script.
- `backups/` — the former root-level `backups/` folder, consolidated here.
- `root/` — old README, a stray `tree` dump, a sample generated report, and an
  unused root-level `package.json`/`package-lock.json` (the real frontend deps live
  in `frontend/package.json`; all build scripts `cd frontend` before running npm).

## Deliberately NOT archived

- `app/api/token.json` — contains a live JWT. Recommend rotating the signing secret
  and deleting the file rather than archiving it (archiving doesn't remove it from
  git history).
- `backup_fim.sh` (root) — contains a hardcoded plaintext DB password. Superseded by
  `scripts/backup-complete-fim-local.sh` (uses `.pgpass`), but left in place pending
  a decision on rotating the exposed password. Update 2026-08-11: found this isn't
  the only superseded variant — `scripts/setup_backups.sh` and an untracked script
  live at `/opt/fim/fim-backups/scripts/` on a real deployment (also hardcoded
  password) are two more. Recommend standardizing on `gap16_backup_encryption.sh`'s
  mechanism instead (real GPG encryption + verified restore, no stored password at
  all — peer auth). See `docs/PRODUCTION_DEPLOYMENT.md` §13 for the full comparison.
- `go-agent/fim-agent-go` — a committed compiled binary; kept as-is since it's a
  deploy artifact, not dead code.
- `load_test.py` (root) — an active dev/test tool.
