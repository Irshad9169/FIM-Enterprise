"""
FIM Server - Main Application
"""
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, FileResponse
from contextlib import asynccontextmanager
import logging
import time
import os

from app.core.config import settings
from app.core.database import db_manager

# Import API routers
from app.api import health, auth, agents, alerts, scans, baselines, alert_actions, agent_health

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan events"""
    logger.info(f"Starting {settings.app_name} v{settings.app_version}")
    await db_manager.initialize()
    yield
    await db_manager.close()


app = FastAPI(
    title=settings.app_name,
    version=settings.app_version,
    docs_url="/api/docs",
    redoc_url="/api/redoc",
    openapi_url="/api/openapi.json",
    lifespan=lifespan
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.middleware("http")
async def log_requests(request: Request, call_next):
    """Log all HTTP requests"""
    start_time = time.time()
    response = await call_next(request)
    duration = time.time() - start_time

    # Log all requests except health checks
    if not request.url.path.endswith("/health"):
        logger.info(
            f"{request.method} {request.url.path} -> "
            f"{response.status_code} ({duration:.3f}s)"
        )

    return response


@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception):
    """Global exception handler"""
    logger.error(f"Unhandled exception: {exc}", exc_info=True)
    return JSONResponse(
        status_code=500,
        content={"error": "Internal server error"}
    )


# Include API routers
app.include_router(health.router, prefix="/api/v1/health", tags=["health"])
app.include_router(auth.router, prefix="/api/v1/auth", tags=["auth"])
app.include_router(agents.router, prefix="/api/v1/agents", tags=["agents"])
app.include_router(alerts.router, prefix="/api/v1/alerts", tags=["alerts"])
app.include_router(scans.router, prefix="/api/v1/scans", tags=["scans"])
app.include_router(baselines.router, prefix="/api/v1/baselines", tags=["baselines"])
app.include_router(alert_actions.router, prefix="/api/v1/alerts/actions", tags=["alert-actions"])
app.include_router(agent_health.router, prefix="/api/v1/agents/health", tags=["agent-health"])

@app.get("/")
async def root():
    """Root endpoint - redirect to frontend"""
    WEB_DIR = "/opt/fim/web"
    index_path = os.path.join(WEB_DIR, "index.html")
    
    if os.path.exists(index_path):
        return FileResponse(index_path)
    else:
        return {
            "name": settings.app_name,
            "version": settings.app_version,
            "status": "running",
            "message": "Frontend not built. Run: /opt/fim/scripts/build-frontend.sh"
        }


@app.get("/api/v1")
async def api_root():
    """API v1 root"""
    return {
        "message": "FIM API v1",
        "docs": "/api/docs",
        "health": "/api/v1/health"
    }


# Serve Next.js static files for all other routes
WEB_DIR = "/opt/fim/web"

@app.get("/{full_path:path}")
async def serve_spa(full_path: str):
    """Serve Next.js SPA with proper routing"""
    
    # Skip API routes
    if full_path.startswith("api/"):
        from fastapi import HTTPException
        raise HTTPException(status_code=404, detail="API endpoint not found")
    
    # Try to serve exact file
    file_path = os.path.join(WEB_DIR, full_path)
    
    if os.path.isfile(file_path):
        return FileResponse(file_path)
    
    # Try with .html extension
    html_path = file_path + ".html"
    if os.path.isfile(html_path):
        return FileResponse(html_path)
    
    # Check for directory index
    index_path = os.path.join(file_path, "index.html")
    if os.path.isfile(index_path):
        return FileResponse(index_path)
    
    # Check for Next.js route (e.g., login.html, dashboard.html)
    route_html = os.path.join(WEB_DIR, full_path.split('/')[0] + ".html")
    if os.path.isfile(route_html):
        return FileResponse(route_html)
    
    # Fallback to root index.html for SPA client-side routing
    root_index = os.path.join(WEB_DIR, "index.html")
    if os.path.isfile(root_index):
        return FileResponse(root_index)
    
    # Nothing found
    from fastapi import HTTPException
    raise HTTPException(status_code=404, detail="Page not found")
