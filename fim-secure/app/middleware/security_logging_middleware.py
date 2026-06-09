"""
Security Event Logging Middleware — GAP #14
Intercepts all responses and logs 401/403 events with full context.
This single middleware covers every endpoint automatically.
"""

import logging
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response
from app.core.security_logger import log_unauthorized, log_forbidden

logger = logging.getLogger(__name__)

# Paths to skip logging (noise suppression)
SKIP_LOG_PREFIXES = [
    "/api/v1/health",
    "/docs",
    "/openapi.json",
    "/static",
]


class SecurityLoggingMiddleware(BaseHTTPMiddleware):
    """
    Log all 401 and 403 responses with request context.
    Helps detect brute-force, unauthorized access, and CSRF attack patterns.
    """

    async def dispatch(self, request: Request, call_next) -> Response:
        response = await call_next(request)

        # Only log security-relevant status codes
        if response.status_code not in (401, 403):
            return response

        # Skip noise paths
        path = request.url.path
        for prefix in SKIP_LOG_PREFIXES:
            if path.startswith(prefix):
                return response

        ip = (
            request.headers.get("x-forwarded-for", "").split(",")[0].strip()
            or (request.client.host if request.client else "unknown")
        )
        method = request.method
        user_id = ""

        # Try to extract user_id from request state (set by auth middleware)
        try:
            user_id = str(getattr(request.state, "user_id", ""))
        except Exception:
            pass

        if response.status_code == 401:
            log_unauthorized(
                path=path, method=method, ip=ip,
                reason="token_invalid_or_revoked"
            )
        elif response.status_code == 403:
            log_forbidden(
                path=path, method=method, ip=ip,
                user_id=user_id,
                reason="csrf_or_permission_denied"
            )

        return response
