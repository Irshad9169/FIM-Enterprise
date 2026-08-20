# FIM Dashboard Quick Reference

⚠️ This file previously described a Next.js app-router frontend and a `fim-server`
service — neither matches this codebase. The frontend is **Vite + React Router**
(`frontend/src/pages/*.tsx`, routed in `frontend/src/App.tsx`), and the backend
service is `fim-backend` (production) or `fim-backend-test` (a second `FIM_HOME`
instance, if one exists on this box — see `docs/PRODUCTION_DEPLOYMENT.md` §6).
Rewritten below to match reality.

## Build & Deploy

```bash
cd frontend
npm install                 # first time, or after package.json changes
                             # (may need --legacy-peer-deps — see PRODUCTION_DEPLOYMENT.md §7)
npm run build                # outputs to ../web/ (vite.config.ts: build.outDir = '../web')
```

There is no `deploy-dashboard.sh`/`build-frontend.sh` in this repo — `npm run build`
is the whole build step. The backend serves `../web/` directly as static files
(`app/main.py`'s `SPAStaticFiles` mount) — **no restart is needed for a frontend-only
change**, the backend reads whatever's on disk on each request. Only restart the
backend service if you changed Python code:

```bash
systemctl restart fim-backend          # production
systemctl restart fim-backend-test     # if this box runs a second FIM_HOME instance
```

## Development Mode

```bash
cd frontend
npm run dev
# Vite dev server, default port 5173 (not 3000) — check terminal output for the
# actual port and confirm it's in app/main.py's CORS allow_origins list (it's
# hardcoded there, not read from .env — see PRODUCTION_DEPLOYMENT.md §7)
```

## Logs & Monitoring

```bash
journalctl -u fim-backend -f           # application + error logs
journalctl -u fim-backend-test -f      # if using the second instance

systemctl status fim-backend
```

## Troubleshooting

### Frontend not loading / stale after a deploy
```bash
# Confirm the build actually landed where the backend serves from
ls -la web/            # repo root, NOT frontend/dist — vite outputs here directly

# Rebuild
cd frontend && npm run build

# Hard-refresh the browser — the backend needs no restart, but the browser may
# have cached the old JS bundle
```

### API connection / CORS errors
```bash
grep CORS_ORIGINS $FIM_HOME/.env   # default FIM_HOME is /opt/fim
```
As of 2026-08-20, CORS origins are read from `CORS_ORIGINS` in `.env`
(`app/main.py` → `settings.cors_origins`), not hardcoded in source anymore. The
default (no `CORS_ORIGINS` set) is localhost dev-server origins only — a real
deployment's frontend origin must be added explicitly, or every API call fails
silently in the browser console with a CORS error, not a clear "add your origin"
message. Edit `.env` and restart the backend; no source edit needed.

### 500 errors that don't show up in the browser
```bash
journalctl -u fim-backend -n 100 --no-pager
```
Also check **System Health** in the app itself (Administration → System Health,
admin-only) — a full disk will crash Postgres with an unhelpful 500 before any
app-level error message can even form. See `docs/CHANGELOG.md`'s 2026-08-10/11
entries for a real incident that looked like a generic "Internal Server Error"
but was actually the disk at 0 bytes free.

## File Locations

| What | Where |
|---|---|
| Frontend source | `frontend/src/` |
| Built static files (served by backend) | `web/` (repo root, not `frontend/dist`) |
| Backend source | `app/` |
| Backend entrypoint | `app/main.py` |

## Ports

| Service | Port |
|---|---|
| Backend (serves API + built frontend) | 8000 (production) |
| Second `FIM_HOME` instance, if present | 8803 (this box's actual convention — confirm per-deployment, not universal) |
| Vite dev server (`npm run dev`) | 5173 (Vite default) |
| PostgreSQL | 5432 |

## Updating the Frontend

```bash
cd frontend/src
# make code changes under pages/, components/, etc.
cd ..
npm run build
# no backend restart needed — hard-refresh the browser
```
