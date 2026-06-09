"""
Enhanced Authentication
"""
from fastapi import APIRouter, Depends, HTTPException, status, Request, Response
from sqlalchemy.ext.asyncio import AsyncSession
from datetime import datetime
from sqlalchemy import select
from pydantic import BaseModel
from datetime import timedelta
from app.core.database import get_db
from app.core.security import verify_password, create_access_token
from app.core.config import settings
from app.models import User
from app.services.audit_service import AuditService
from app.services.session_service import SessionService
from app.core.security_logger import log_login_failed, log_login_success
from app.middleware.csrf_middleware import generate_csrf_token, set_csrf_cookie

router = APIRouter()

class LoginRequest(BaseModel):
    username: str
    password: str

class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    user: dict

# Simple permissions structure
from app.middleware.rbac import ROLE_PERMISSIONS


def _client_ip(request: Request) -> str:
    forwarded = request.headers.get("x-forwarded-for")
    if forwarded:
        return forwarded.split(",")[0].strip()
    return request.client.host if request.client else ""


@router.post("/login", response_model=TokenResponse)
async def login(response: Response,
    
    request: LoginRequest,
    http_request: Request,
    db: AsyncSession = Depends(get_db)
):
    """User login"""
    try:
        # Find user
        result = await db.execute(
            select(User).where(User.username == request.username)
        )
        user = result.scalar_one_or_none()

        if not user or not verify_password(request.password, user.password_hash):
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Incorrect username or password",
                headers={"WWW-Authenticate": "Bearer"},
            )

        if not user.is_active:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="User account is disabled"
            )

        # Create access token
        access_token_expires = timedelta(minutes=settings.access_token_expire_minutes)
        access_token = create_access_token(
            data={
                "sub": str(user.id),
                "username": user.username,
                "role": user.role
            },
            expires_delta=access_token_expires
        )

        # Track session
        from jose import jwt as jose_jwt
        token_payload = jose_jwt.decode(access_token, "dummy", algorithms=["HS256"], options={"verify_signature": False})
        await SessionService.create_session(
            db, str(user.id), token_payload.get("jti", ""),
            expires_at=datetime.utcnow() + access_token_expires,
            ip_address=_client_ip(http_request),
            user_agent=http_request.headers.get("user-agent", "")[:200],
        )

        # Audit log: LOGIN
        await AuditService.log(
            db, user.id, user.username, "LOGIN",
            details={"method": "password"},
            ip_address=_client_ip(http_request),
        )
        await db.commit()

        # GAP #13: set CSRF token cookie on successful login
        _csrf_tok = generate_csrf_token()
        set_csrf_cookie(response, _csrf_tok)

        return {
            "access_token": access_token,
            "token_type": "bearer",
            "user": {
                "id": str(user.id),
                "username": user.username,
                "email": user.email,
                "role": user.role,
                "full_name": user.full_name,
                "permissions": ROLE_PERMISSIONS.get(user.role, {})
            }
        }

    except HTTPException:
        raise
    except Exception as e:
        import traceback
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=f"Login error: {str(e)}")

@router.get("/csrf-token", tags=["auth"])
async def get_csrf_token(response: Response):
    """GAP #13: Return a fresh CSRF token and set it as a cookie."""
    token = generate_csrf_token()
    set_csrf_cookie(response, token)
    return {"csrf_token": token}
