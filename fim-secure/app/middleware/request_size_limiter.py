"""
Request Size Limit Middleware
Prevents DoS attacks via oversized payloads (GAP #7 fix).
"""

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import JSONResponse
from fastapi import Request
import logging

logger = logging.getLogger(__name__)

# Per-endpoint size limits (bytes)
ENDPOINT_SIZE_LIMITS = {
    '/api/v1/scans/submit':  50_000_000,   # 50 MB — scan payloads can be large
    '/api/v1/reports/':      10_000_000,   # 10 MB
    '/api/v1/baselines/':    20_000_000,   # 20 MB
    'default':                5_000_000,   #  5 MB — everything else
}


class RequestSizeLimitMiddleware(BaseHTTPMiddleware):
    """
    Enforce request body size limits per endpoint.
    Rejects oversized requests with HTTP 413 before the body is read.
    """

    async def dispatch(self, request: Request, call_next):
        content_length = request.headers.get('content-length')

        if content_length:
            try:
                content_length = int(content_length)
            except ValueError:
                return JSONResponse(
                    status_code=400,
                    content={"detail": "Invalid Content-Length header"}
                )

            # Resolve limit for this path
            path = request.url.path
            limit = ENDPOINT_SIZE_LIMITS['default']
            for pattern, endpoint_limit in ENDPOINT_SIZE_LIMITS.items():
                if pattern != 'default' and path.startswith(pattern):
                    limit = endpoint_limit
                    break

            if content_length > limit:
                logger.warning(
                    "Request size limit exceeded: %d bytes (limit: %d) "
                    "from %s to %s",
                    content_length, limit,
                    request.client.host if request.client else "unknown",
                    path,
                )
                return JSONResponse(
                    status_code=413,
                    content={
                        "detail": (
                            f"Request body too large. "
                            f"Maximum allowed for this endpoint: "
                            f"{limit / 1_000_000:.0f} MB"
                        )
                    },
                )

        return await call_next(request)
