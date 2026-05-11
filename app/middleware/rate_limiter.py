"""
API Rate Limiting Middleware

Limits requests per IP address using a sliding window counter.
Configurable per-path limits.

Default limits:
  - /api/v1/auth/login:     5 requests per minute (brute force protection)
  - /api/v1/scans/submit:   30 per minute (agent submissions)
  - /api/v1/* (general):    120 per minute
"""
import time
import logging
from collections import defaultdict
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import JSONResponse

logger = logging.getLogger("rate_limiter")

# Rate limit config: path_prefix -> (max_requests, window_seconds)
RATE_LIMITS = {
    "/api/v1/auth/login": (5, 60),
    "/api/v1/scans/submit": (30, 60),
    "/api/v1/agents/register": (10, 60),
}
DEFAULT_LIMIT = (120, 60)


class RateLimiterMiddleware(BaseHTTPMiddleware):

    def __init__(self, app):
        super().__init__(app)
        # {(ip, path_prefix): [(timestamp, ...)] }
        self._requests: dict = defaultdict(list)
        self._last_cleanup = time.time()

    def _get_client_ip(self, request) -> str:
        forwarded = request.headers.get("x-forwarded-for")
        if forwarded:
            return forwarded.split(",")[0].strip()
        return request.client.host if request.client else "unknown"

    def _get_limit(self, path: str):
        for prefix, limit in RATE_LIMITS.items():
            if path.startswith(prefix):
                return limit
        if path.startswith("/api/"):
            return DEFAULT_LIMIT
        return None  # No limit for non-API paths

    def _cleanup(self):
        """Remove old entries every 60 seconds."""
        now = time.time()
        if now - self._last_cleanup < 60:
            return
        cutoff = now - 120
        to_delete = [k for k, v in self._requests.items() if not v or v[-1] < cutoff]
        for k in to_delete:
            del self._requests[k]
        self._last_cleanup = now

    async def dispatch(self, request, call_next):
        path = request.url.path.rstrip("/")
        limit = self._get_limit(path)

        if not limit:
            return await call_next(request)

        max_requests, window = limit
        ip = self._get_client_ip(request)
        key = (ip, path.split("?")[0])
        now = time.time()

        # Cleanup periodically
        self._cleanup()

        # Slide window
        cutoff = now - window
        self._requests[key] = [t for t in self._requests[key] if t > cutoff]

        if len(self._requests[key]) >= max_requests:
            logger.warning(f"Rate limit exceeded: ip={ip} path={path} limit={max_requests}/{window}s")
            return JSONResponse(
                status_code=429,
                content={"error": "Too many requests", "retry_after": window},
                headers={"Retry-After": str(window)}
            )

        self._requests[key].append(now)
        response = await call_next(request)
        return response
