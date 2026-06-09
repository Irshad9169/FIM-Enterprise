"""
Enhanced Audit Logging Service
"""
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import insert
from app.models import AuditLog
from typing import Optional, Dict
import uuid
from datetime import datetime

class AuditService:
    """
    Centralized audit logging service
    """
    
    @staticmethod
    async def log(
        db: AsyncSession,
        user_id: Optional[uuid.UUID],
        username: Optional[str],
        action: str,
        resource_type: Optional[str] = None,
        resource_id: Optional[uuid.UUID] = None,
        details: Optional[Dict] = None,
        ip_address: Optional[str] = None,
        user_agent: Optional[str] = None
    ):
        """
        Log an audit entry
        
        Args:
            db: Database session
            user_id: User UUID
            username: Username
            action: Action performed (e.g., 'login', 'report_generated', 'alert_acknowledged')
            resource_type: Type of resource (e.g., 'report', 'alert', 'agent')
            resource_id: Resource UUID
            details: Additional details as JSON
            ip_address: Client IP
            user_agent: Client user agent
        """
        audit_entry = AuditLog(
            id=uuid.uuid4(),
            user_id=user_id,
            username=username,
            action=action,
            resource_type=resource_type,
            resource_id=resource_id,
            details=details,
            ip_address=ip_address,
            user_agent=user_agent,
            timestamp=datetime.utcnow()
        )
        
        db.add(audit_entry)
        # Note: Caller is responsible for commit
    
    # Convenience methods for common actions
    
    @staticmethod
    async def log_login(db: AsyncSession, user_id: uuid.UUID, username: str, ip_address: str):
        await AuditService.log(
            db, user_id, username, 'login', 
            ip_address=ip_address
        )
    
    @staticmethod
    async def log_logout(db: AsyncSession, user_id: uuid.UUID, username: str):
        await AuditService.log(
            db, user_id, username, 'logout'
        )
    
    @staticmethod
    async def log_report_generated(
        db: AsyncSession, 
        user_id: uuid.UUID, 
        username: str, 
        report_id: uuid.UUID,
        report_type: str,
        date: str
    ):
        await AuditService.log(
            db, user_id, username, 'report_generated',
            resource_type='report',
            resource_id=report_id,
            details={'report_type': report_type, 'date': date}
        )
    
    @staticmethod
    async def log_report_reviewed(
        db: AsyncSession,
        user_id: uuid.UUID,
        username: str,
        report_id: uuid.UUID,
        group_id: uuid.UUID,
        is_known: bool
    ):
        await AuditService.log(
            db, user_id, username, 'report_reviewed',
            resource_type='correlation_group',
            resource_id=group_id,
            details={'report_id': str(report_id), 'is_known': is_known}
        )
    
    @staticmethod
    async def log_report_submitted(
        db: AsyncSession,
        user_id: uuid.UUID,
        username: str,
        report_id: uuid.UUID,
        rt_ticket_id: Optional[str]
    ):
        await AuditService.log(
            db, user_id, username, 'report_submitted',
            resource_type='report',
            resource_id=report_id,
            details={'rt_ticket_id': rt_ticket_id}
        )
    
    @staticmethod
    async def log_scan_triggered(
        db: AsyncSession,
        user_id: uuid.UUID,
        username: str,
        agent_id: uuid.UUID,
        agent_hostname: str
    ):
        await AuditService.log(
            db, user_id, username, 'scan_triggered',
            resource_type='agent',
            resource_id=agent_id,
            details={'agent_hostname': agent_hostname}
        )
    
    @staticmethod
    async def log_alert_acknowledged(
        db: AsyncSession,
        user_id: uuid.UUID,
        username: str,
        alert_id: uuid.UUID
    ):
        await AuditService.log(
            db, user_id, username, 'alert_acknowledged',
            resource_type='alert',
            resource_id=alert_id
        )
    
    @staticmethod
    async def log_baseline_approved(
        db: AsyncSession,
        user_id: uuid.UUID,
        username: str,
        baseline_id: uuid.UUID
    ):
        await AuditService.log(
            db, user_id, username, 'baseline_approved',
            resource_type='baseline',
            resource_id=baseline_id
        )
