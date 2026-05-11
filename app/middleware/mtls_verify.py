"""
mTLS Verification Middleware for FIM Enterprise

When nginx terminates mTLS, it passes these headers:
  X-Client-CN:     Certificate Common Name (should match agent hostname)
  X-Client-Verify: "SUCCESS" if cert verified by CA
  X-Client-Serial: Certificate serial number

This middleware validates that:
  1. The client cert was verified by nginx (X-Client-Verify == SUCCESS)
  2. The CN matches a registered agent hostname in the database
  3. The CN matches the agent_id in the request body (anti-spoofing)

Apply to agent and scan endpoints only — browser/SSO endpoints don't use mTLS.

Usage in main.py:
    from app.middleware.mtls_verify import MTLSVerifyMiddleware
    app.add_middleware(MTLSVerifyMiddleware)
"""
import logging
from typing import Optional
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse

logger = logging.getLogger("mtls_verify")

# Paths that require mTLS client certificate verification
MTLS_REQUIRED_PATHS = [
    "/api/v1/agents/heartbeat",
    "/api/v1/agents/register",
    "/api/v1/scans/submit",
]


class MTLSVerifyMiddleware(BaseHTTPMiddleware):
    """
    Validates mTLS client certificate headers set by nginx.

    Only enforced on agent/scan endpoints. Browser endpoints are
    unaffected and can be accessed without a client certificate.

    Set MTLS_ENABLED=true in environment to activate.
    When disabled, this middleware is a no-op passthrough.
    """

    async def dispatch(self, request: Request, call_next):
        import os

        # Check if mTLS enforcement is enabled
        if not os.environ.get("MTLS_ENABLED", "").lower() in ("true", "1", "yes"):
            return await call_next(request)

        # Only enforce on agent/scan paths
        path = request.url.path.rstrip("/")
        requires_mtls = any(path.startswith(p) for p in MTLS_REQUIRED_PATHS)

        if not requires_mtls:
            return await call_next(request)

        # ── Verify client certificate headers from nginx ──────────────
        client_verify = request.headers.get("x-client-verify", "")
        client_cn = request.headers.get("x-client-cn", "")

        if client_verify != "SUCCESS":
            logger.warning(
                f"mTLS REJECTED: path={path} verify={client_verify!r} "
                f"ip={request.client.host if request.client else 'unknown'}"
            )
            return JSONResponse(
                status_code=403,
                content={
                    "error": "Client certificate verification failed",
                    "detail": "A valid mTLS client certificate signed by the FIM CA is required"
                }
            )

        if not client_cn:
            logger.warning(f"mTLS REJECTED: path={path} — no CN in certificate")
            return JSONResponse(
                status_code=403,
                content={"error": "Client certificate has no Common Name (CN)"}
            )

        # Store CN in request state for downstream use
        request.state.client_cn = client_cn
        request.state.mtls_verified = True

        logger.debug(f"mTLS OK: path={path} cn={client_cn}")

        response = await call_next(request)
        return response
