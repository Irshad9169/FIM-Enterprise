"""
MFA Endpoints — GAP #20
Enable, confirm, verify, disable TOTP for users.
"""
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, text
from pydantic import BaseModel
from app.core.database import get_db
from app.core.security import get_current_user, create_access_token
from app.core.mfa import (
    generate_totp_secret, encrypt_secret, decrypt_secret,
    generate_qr_base64, verify_totp
)
from app.models import User
from datetime import timedelta
from app.core.config import settings

router = APIRouter()

class MFACodeRequest(BaseModel):
    code: str

class MFAVerifyRequest(BaseModel):
    username: str
    password: str
    code: str

@router.post("/enable")
async def enable_mfa(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Generate TOTP secret and return QR code. User must confirm before MFA is active."""
    secret = generate_totp_secret()
    encrypted = encrypt_secret(secret)

    await db.execute(text("""
        UPDATE fim.users
        SET mfa_secret = :secret, mfa_enabled = false, mfa_confirmed = false
        WHERE id = :id
    """), {"secret": encrypted, "id": str(current_user.id)})
    await db.commit()

    qr_b64 = generate_qr_base64(secret, current_user.username)
    return {
        "message": "Scan QR code in Google Authenticator then confirm with a valid code",
        "qr_code": f"data:image/png;base64,{qr_b64}",
        "secret": secret,  # show once for manual entry
        "next_step": "POST /api/v1/mfa/confirm with your 6-digit code"
    }


@router.post("/confirm")
async def confirm_mfa(
    req: MFACodeRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Confirm TOTP setup with first valid code — activates MFA."""
    result = await db.execute(
        select(User).where(User.id == current_user.id)
    )
    user = result.scalar_one_or_none()
    if not user or not user.mfa_secret:
        raise HTTPException(400, "MFA setup not initiated — call /enable first")

    if not verify_totp(user.mfa_secret, req.code):
        raise HTTPException(400, "Invalid code — check your authenticator app and try again")

    await db.execute(text("""
        UPDATE fim.users SET mfa_enabled = true, mfa_confirmed = true WHERE id = :id
    """), {"id": str(user.id)})
    await db.commit()

    return {"message": "MFA enabled successfully", "mfa_enabled": True}


@router.post("/disable")
async def disable_mfa(
    req: MFACodeRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user)
):
    """Disable MFA — requires valid code to prevent account takeover."""
    result = await db.execute(select(User).where(User.id == current_user.id))
    user = result.scalar_one_or_none()

    if not user or not user.mfa_enabled:
        raise HTTPException(400, "MFA is not enabled")
    if not verify_totp(user.mfa_secret, req.code):
        raise HTTPException(400, "Invalid code")

    await db.execute(text("""
        UPDATE fim.users
        SET mfa_enabled = false, mfa_confirmed = false, mfa_secret = null
        WHERE id = :id
    """), {"id": str(user.id)})
    await db.commit()
    return {"message": "MFA disabled"}


@router.get("/status")
async def mfa_status(
    current_user: User = Depends(get_current_user)
):
    """Get MFA status for current user."""
    return {
        "mfa_enabled": getattr(current_user, 'mfa_enabled', False),
        "mfa_confirmed": getattr(current_user, 'mfa_confirmed', False),
    }


@router.post("/verify")
async def verify_mfa(
    req: MFAVerifyRequest,
    db: AsyncSession = Depends(get_db)
):
    """
    Second factor verification after password check.
    Called when login returns mfa_required=true.
    Returns full JWT on success.
    """
    from app.core.security import verify_password
    result = await db.execute(
        select(User).where(User.username == req.username)
    )
    user = result.scalar_one_or_none()
    if not user or not verify_password(req.password, user.password_hash):
        raise HTTPException(401, "Invalid credentials")
    if not user.mfa_enabled or not user.mfa_confirmed:
        raise HTTPException(400, "MFA not configured for this user")
    if not verify_totp(user.mfa_secret, req.code):
        raise HTTPException(401, "Invalid MFA code")

    access_token = create_access_token(
        data={"sub": str(user.id), "username": user.username, "role": user.role},
        expires_delta=timedelta(minutes=settings.access_token_expire_minutes)
    )
    return {
        "access_token": access_token,
        "token_type": "bearer",
        "user": {"id": str(user.id), "username": user.username, "role": user.role}
    }
