"""
CSRF Protection Middleware — GAP #13
Strategy: Double Submit Cookie

How it works:
  1. On login response, server sets csrf_token cookie (SameSite=Strict, not HttpOnly)
  2. Frontend JS reads the cookie and sends it as X-CSRF-Token header
  3. This middleware validates header == cookie on all state-changing requests
  4. A cross-origin attacker cannot read the cookie, so cannot forge the header

Safe methods (GET, HEAD, OPTIONS) are always allowed.
Exempt paths bypass the check (agent traffic, login endpoint).
"""

import secrets
import logging
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse, Response

logger = logging.getLogger(__name__)

# Methods that never cause state changes — always exempt
SAFE_METHODS = {"GET", "HEAD", "OPTIONS"}

# Paths that bypass CSRF (no browser session exists yet, or agent traffic)
EXEMPT_PREFIXES = [
    "/api/v1/auth/login",
    "/api/v1/auth/sso",
    "/api/v1/auth/refresh",
    "/api/v1/agents/register",
    "/api/v1/agents/heartbeat",
    "/api/v1/agents/scan",        # Scan trigger endpoint
    "/api/v1/scans/submit",
    "/api/v1/health",
    "/docs",
    "/openapi.json",
    "/static",
]

CSRF_COOKIE_NAME  = "csrf_token"
CSRF_HEADER_NAME  = "x-csrf-token"
CSRF_TOKEN_LENGTH = 32   # bytes → 64 hex chars


class CSRFMiddleware(BaseHTTPMiddleware):
    """
    Double-submit cookie CSRF protection.
    Rejects state-changing requests where the X-CSRF-Token header
    does not match the csrf_token cookie.
    """

    async def dispatch(self, request: Request, call_next) -> Response:
        # Safe methods never need CSRF check
        if request.method in SAFE_METHODS:
            return await call_next(request)

        # Exempt paths bypass the check
        path = request.url.path
        for prefix in EXEMPT_PREFIXES:
            if path.startswith(prefix):
                return await call_next(request)
        
        # Special handling for paths with UUIDs like /api/v1/agents/{uuid}/scan
        if path.startswith("/api/v1/agents/") and "/scan" in path:
            return await call_next(request)

        # Skip CSRF for authenticated API endpoints (JWT token in Authorization header)
        auth_header = request.headers.get("authorization", "")
        if auth_header.startswith("Bearer "):
            return await call_next(request)
        
        # Skip CSRF for authenticated API endpoints (with Bearer token)
        auth_header = request.headers.get("authorization", "")
        if auth_header.startswith("Bearer "):
            # User is authenticated via JWT, skip CSRF for API calls
            return await call_next(request)

        # Validate double-submit
        cookie_token  = request.cookies.get(CSRF_COOKIE_NAME, "")
        header_token  = request.headers.get(CSRF_HEADER_NAME, "")

        if not cookie_token or not header_token:
            logger.warning(
                "CSRF: missing token | path=%s method=%s "
                "cookie_present=%s header_present=%s client=%s",
                path, request.method,
                bool(cookie_token), bool(header_token),
                request.client.host if request.client else "unknown",
            )
            return JSONResponse(
                status_code=403,
                content={
                    "detail": "CSRF token missing. "
                              "Include X-CSRF-Token header matching the csrf_token cookie."
                },
            )

        # Constant-time comparison — prevents timing attacks
        if not secrets.compare_digest(cookie_token, header_token):
            logger.warning(
                "CSRF: token mismatch | path=%s method=%s client=%s",
                path, request.method,
                request.client.host if request.client else "unknown",
            )
            return JSONResponse(
                status_code=403,
                content={"detail": "CSRF token mismatch."},
            )

        return await call_next(request)


def generate_csrf_token() -> str:
    """Generate a new CSRF token. Call this on login and attach to response."""
    return secrets.token_hex(CSRF_TOKEN_LENGTH)


def set_csrf_cookie(response: Response, token: str) -> None:
    """
    Attach the CSRF token as a cookie on a response.
    NOT HttpOnly so JS can read it. SameSite=Strict for extra protection.
    """
    response.set_cookie(
        key=CSRF_COOKIE_NAME,
        value=token,
        httponly=False,       # JS must read this to send as header
        samesite="strict",    # Extra layer: browser blocks cross-site sends
        secure=False,         # Set True when HTTPS (GAP #2) is active
        path="/",
        max_age=86400,        # 24 hours — match JWT expiry
    )
