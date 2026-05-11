from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import RedirectResponse
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
import logging
import json
from app.core.database import get_db
from app.core.security import create_access_token
from app.middleware.csrf_middleware import generate_csrf_token, set_csrf_cookie
from app.models.models import User
from app.core.sso_manager import SSOManager
from app.services.audit_service import AuditService
from app.services.session_service import SessionService
from datetime import datetime, timedelta

logger = logging.getLogger("sso_debug")
router = APIRouter()
sso = SSOManager()


def _client_ip(request: Request) -> str:
    forwarded = request.headers.get("x-forwarded-for")
    if forwarded:
        return forwarded.split(",")[0].strip()
    return request.client.host if request.client else ""


@router.get("/login")
async def sso_login(request: Request):
    host = request.headers.get('host')
    callback_url = f"http://{host}/api/v1/sso/callback"
    return RedirectResponse(url=sso.get_login_url(callback_url))


@router.get("/callback")
async def auth_callback(request: Request, db: AsyncSession = Depends(get_db)):
    token_str = request.query_params.get("sso_token")
    if not token_str:
        return RedirectResponse(url="/login?error=no_sso_token")

    username = sso.get_user_from_token(token_str)
    if not username:
        return RedirectResponse(url="/login?error=invalid_sso_token")

    # Check if user is pre-registered in the DB
    res = await db.execute(select(User).where(User.username == username))
    user = res.scalar_one_or_none()

    if not user:
        logger.warning(f"Unauthorized SSO attempt: {username} is not registered.")
        return RedirectResponse(url="/login?error=unauthorized_user")

    if not user.is_active:
        return RedirectResponse(url="/login?error=account_disabled")

    # Issue FIM JWT
    access_token = create_access_token(data={"sub": str(user.id), "username": user.username, "role": user.role})
    user_data = json.dumps({"username": user.username, "role": user.role, "email": user.email})

    # Track session
    from jose import jwt as jose_jwt
    from app.core.config import settings
    token_payload = jose_jwt.decode(access_token, "dummy", algorithms=["HS256"], options={"verify_signature": False})
    await SessionService.create_session(
        db, str(user.id), token_payload.get("jti", ""),
        expires_at=datetime.utcnow() + timedelta(minutes=settings.access_token_expire_minutes),
        ip_address=_client_ip(request),
        user_agent=request.headers.get("user-agent", "")[:200],
    )
    # Audit log: LOGIN
    await AuditService.log(
        db, user.id, user.username, "LOGIN",
        details={"method": "sso"},
        ip_address=_client_ip(request),
    )
    await db.commit()

    _csrf_tok = generate_csrf_token()
    _sso_response = RedirectResponse(
        url=f"/login?sso_token={access_token}&sso_user={user_data}")
    set_csrf_cookie(_sso_response, _csrf_tok)
    return _sso_response
