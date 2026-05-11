from fastapi import HTTPException, Depends
from app.core.security import get_current_user
from app.models.models import User

# Legacy support for existing modules like scan_requests.py
def require_role(required_role: str):
    def role_checker(current_user: User = Depends(get_current_user)):
        if current_user.role != 'admin' and current_user.role != required_role:
            raise HTTPException(status_code=403, detail=f"Requires {required_role} privileges")
        return current_user
    return role_checker

# New simplified helpers
def admin_only(current_user: User = Depends(get_current_user)):
    if current_user.role != 'admin':
        raise HTTPException(status_code=403, detail="Administration privileges required")
    return current_user

def analyst_plus(current_user: User = Depends(get_current_user)):
    if current_user.role not in ['admin', 'analyst']:
        raise HTTPException(status_code=403, detail="Analyst or Admin privileges required")
    return current_user
