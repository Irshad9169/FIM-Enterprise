"""
Session Management Service

Tracks active JWT sessions in the database.
Allows admins to view and revoke sessions.
"""
import logging
from datetime import datetime
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger("session_service")


class SessionService:

    @staticmethod
    async def create_session(
        db: AsyncSession, user_id: str, token_jti: str,
        expires_at: datetime, ip_address: str = None, user_agent: str = None
    ):
        """Record a new session when a token is issued."""
        await db.execute(text("""
            INSERT INTO fim.sessions (user_id, token_jti, ip_address, user_agent, expires_at)
            VALUES (:user_id, :jti, :ip, :ua, :expires)
        """), {
            "user_id": user_id, "jti": token_jti,
            "ip": ip_address, "ua": user_agent, "expires": expires_at
        })

        # Update user last_login
        await db.execute(text("""
            UPDATE fim.users SET last_login = NOW(), last_login_ip = :ip WHERE id = :uid
        """), {"ip": ip_address, "uid": user_id})

    @staticmethod
    async def is_session_valid(db: AsyncSession, token_jti: str) -> bool:
        """Check if a session is still valid (not revoked, not expired)."""
        result = await db.execute(text("""
            SELECT 1 FROM fim.sessions
            WHERE token_jti = :jti AND is_revoked = false AND expires_at > NOW()
        """), {"jti": token_jti})
        return result.scalar() is not None

    @staticmethod
    async def update_activity(db: AsyncSession, token_jti: str):
        """Update last activity timestamp."""
        await db.execute(text("""
            UPDATE fim.sessions SET last_activity = NOW() WHERE token_jti = :jti
        """), {"jti": token_jti})

    @staticmethod
    async def revoke_session(db: AsyncSession, session_id: str, revoked_by: str):
        """Revoke a specific session."""
        await db.execute(text("""
            UPDATE fim.sessions
            SET is_revoked = true, revoked_at = NOW(), revoked_by = :by
            WHERE id = :id
        """), {"id": session_id, "by": revoked_by})

    @staticmethod
    async def revoke_all_user_sessions(db: AsyncSession, user_id: str, revoked_by: str):
        """Revoke all sessions for a user (force logout)."""
        await db.execute(text("""
            UPDATE fim.sessions
            SET is_revoked = true, revoked_at = NOW(), revoked_by = :by
            WHERE user_id = :uid AND is_revoked = false
        """), {"uid": user_id, "by": revoked_by})

    @staticmethod
    async def get_user_sessions(db: AsyncSession, user_id: str):
        """Get all active sessions for a user."""
        result = await db.execute(text("""
            SELECT id, ip_address, user_agent, created_at, last_activity, expires_at, is_revoked
            FROM fim.sessions
            WHERE user_id = :uid
            ORDER BY created_at DESC
            LIMIT 20
        """), {"uid": user_id})
        return [dict(row._mapping) for row in result.fetchall()]

    @staticmethod
    async def get_all_active_sessions(db: AsyncSession):
        """Get all active sessions (admin view)."""
        result = await db.execute(text("""
            SELECT s.id, s.user_id, u.username, s.ip_address, s.user_agent,
                   s.created_at, s.last_activity, s.expires_at
            FROM fim.sessions s
            JOIN fim.users u ON s.user_id = u.id
            WHERE s.is_revoked = false AND s.expires_at > NOW()
            ORDER BY s.last_activity DESC
        """))
        return [dict(row._mapping) for row in result.fetchall()]

    @staticmethod
    async def cleanup_expired(db: AsyncSession):
        """Remove expired sessions older than 7 days."""
        await db.execute(text("""
            DELETE FROM fim.sessions
            WHERE expires_at < NOW() - INTERVAL '7 days'
        """))
