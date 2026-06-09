"""
RBAC (Role-Based Access Control) Enforcement

Provides a dependency function to check permissions on endpoints.

Usage:
    from app.middleware.rbac import require_permission

    @router.post("/generate")
    async def generate_report(
        ...,
        _=Depends(require_permission("reports_generate"))
    ):

Roles and permissions:
    admin   : Full access
    analyst : Generate/review/submit reports, trigger scans, approve baselines, manage alerts
    trainee : Review/submit reports, manage alerts (read-heavy, limited write)
    auditor : Read-only access to audit logs
"""
from fastapi import Depends, HTTPException
from app.core.security import get_current_user
from app.models.models import User

ROLE_PERMISSIONS = {
    'admin': {
        'reports_generate': True, 'reports_review': True, 'reports_submit': True,
        'reports_publish': True, 'reports_delete': True, 'reports_archive': True,
        'scans_trigger': True, 'agents_manage': True, 'agents_deploy': True,
        'baselines_approve': True, 'baselines_rebaseline': True,
        'alerts_manage': True, 'alerts_acknowledge': True,
        'exclusions_manage': True,
        'audit_logs_view': True, 'users_manage': True, 'sessions_manage': True,
    },
    'analyst': {
        'reports_generate': True, 'reports_review': True, 'reports_submit': True,
        'reports_publish': True, 'reports_delete': False, 'reports_archive': False,
        'scans_trigger': True, 'agents_manage': False, 'agents_deploy': False,
        'baselines_approve': True, 'baselines_rebaseline': True,
        'alerts_manage': True, 'alerts_acknowledge': True,
        'exclusions_manage': True,
        'audit_logs_view': False, 'users_manage': False, 'sessions_manage': False,
    },
    'trainee': {
        'reports_generate': False, 'reports_review': True, 'reports_submit': True,
        'reports_publish': False, 'reports_delete': False, 'reports_archive': False,
        'scans_trigger': False, 'agents_manage': False, 'agents_deploy': False,
        'baselines_approve': False, 'baselines_rebaseline': False,
        'alerts_manage': False, 'alerts_acknowledge': True,
        'exclusions_manage': False,
        'audit_logs_view': False, 'users_manage': False, 'sessions_manage': False,
    },
    'auditor': {
        'reports_generate': False, 'reports_review': True, 'reports_submit': False,
        'reports_publish': False, 'reports_delete': False, 'reports_archive': False,
        'scans_trigger': False, 'agents_manage': False, 'agents_deploy': False,
        'baselines_approve': False, 'baselines_rebaseline': False,
        'alerts_manage': False, 'alerts_acknowledge': False,
        'exclusions_manage': False,
        'audit_logs_view': True, 'users_manage': False, 'sessions_manage': False,
    },
}


def require_permission(permission: str):
    """FastAPI dependency that checks if current user has the required permission."""
    async def check(current_user: User = Depends(get_current_user)):
        user_perms = ROLE_PERMISSIONS.get(current_user.role, {})
        if not user_perms.get(permission, False):
            raise HTTPException(
                403,
                f"Permission denied: '{permission}' requires role with higher privileges. "
                f"Your role: {current_user.role}"
            )
        return current_user
    return check
