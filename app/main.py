from fastapi import FastAPI, APIRouter, Request
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse, JSONResponse
from fastapi.middleware.cors import CORSMiddleware
from app.middleware.mtls_verify import MTLSVerifyMiddleware  # Enable when mTLS is ready
from app.services.report_scheduler import ReportScheduler
from app.middleware.rate_limiter import RateLimiterMiddleware
from app.middleware.csrf_middleware import CSRFMiddleware
from app.middleware.security_logging_middleware import SecurityLoggingMiddleware
from app.middleware.security_headers_middleware import SecurityHeadersMiddleware
from app.middleware.request_size_limiter import RequestSizeLimitMiddleware
from contextlib import asynccontextmanager
import os
import logging
from app.core.config import settings
from app.core.database import db_manager

# Import routers
from app.api import (
    sessions,
    health, auth_enhanced as auth, agents, alerts, scans,
    baselines, dashboard, reports, exclusions,
    users, audit, integrations, auth_sso,
    anomalies)

# Setup specialized logger for routing debug
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("router_debug")

# Report auto-generation scheduler
scheduler = ReportScheduler()


@asynccontextmanager
async def lifespan(app: FastAPI):
    await db_manager.initialize()
    await scheduler.start()
    yield
    scheduler.stop()
    await db_manager.close()


app = FastAPI(lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    # GAP #18: explicit origins instead of wildcard "*"
    allow_origins=['https://test06.hyd.int.untd.com', 'http://test06.hyd.int.untd.com', 'http://localhost:5173', 'http://localhost:3000', 'http://localhost:8080'],
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
    allow_headers=[
        "Authorization",
        "Content-Type",
        "X-CSRF-Token",
        "X-API-Key",
        "X-Requested-With",
    ],
    expose_headers=["X-Total-Count"],
    max_age=600,  # preflight cache 10 minutes
)

# Rate limiting
app.add_middleware(RateLimiterMiddleware)
app.add_middleware(RequestSizeLimitMiddleware)
app.add_middleware(CSRFMiddleware)
app.add_middleware(SecurityLoggingMiddleware)
app.add_middleware(SecurityHeadersMiddleware)

# mTLS verification — uncomment when certificates are deployed
app.add_middleware(MTLSVerifyMiddleware)

# === API ROUTES ===
logger.info("Registering API routers...")
app.include_router(health.router, prefix="/api/v1/health", tags=["health"])
app.include_router(auth.router, prefix="/api/v1/auth", tags=["auth"])
app.include_router(auth_sso.router, prefix="/api/v1/sso", tags=["sso"])
app.include_router(agents.router, prefix="/api/v1/agents", tags=["agents"])
app.include_router(alerts.router, prefix="/api/v1/alerts", tags=["alerts"])
app.include_router(anomalies.router, prefix="/api/v1/anomalies", tags=["anomalies"])
app.include_router(scans.router, prefix="/api/v1/scans", tags=["scans"])
app.include_router(baselines.router, prefix="/api/v1/baselines", tags=["baselines"])
app.include_router(dashboard.router, prefix="/api/v1/dashboard", tags=["dashboard"])
app.include_router(reports.router, prefix="/api/v1/reports", tags=["reports"])
app.include_router(exclusions.router, prefix="/api/v1/exclusions", tags=["exclusions"])
app.include_router(users.router, prefix="/api/v1/users", tags=["users"])
app.include_router(audit.router, prefix="/api/v1/audit", tags=["audit"])
app.include_router(integrations.router, prefix="/api/v1/integrations", tags=["integrations"])
app.include_router(sessions.router, prefix="/api/v1/sessions", tags=["sessions"])


@app.get("/api/debug_routes")
async def debug_routes():
    return [{"path": r.path, "name": r.name} for r in app.routes]


# === STATIC FILES (SPA Support) ===
WEB_DIR = "/opt/fim/web"


class SPAStaticFiles(StaticFiles):
    async def get_response(self, path: str, scope):
        logger.info(f"Static Handler evaluating path: {path} (Original: {scope['path']})")
        if scope['path'].startswith('/api'):
            logger.warning(f"API Route NOT FOUND by FastAPI: {scope['path']}")
            return JSONResponse(status_code=404, content={"detail": f"API route not found: {scope['path']}"})
        try:
            return await super().get_response(path, scope)
        except Exception:
            if os.path.exists(os.path.join(self.directory, "index.html")):
                return FileResponse(os.path.join(self.directory, "index.html"))
            raise


if os.path.exists(WEB_DIR):
    app.mount("/", SPAStaticFiles(directory=WEB_DIR, html=True), name="static")
    logger.info(f"✅ Serving frontend from {WEB_DIR}")
