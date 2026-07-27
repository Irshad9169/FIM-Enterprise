"""
Security Event Logger — GAP #14
Writes structured JSON security events to /var/log/fim-security.log
and standard Python logging simultaneously.

Usage:
    from app.core.security_logger import security_log

    security_log("login_failed", level="WARNING",
                 username="admin", ip="1.2.3.4", reason="invalid_password")
"""

import json
import logging
import logging.handlers
import os
from datetime import datetime, timezone
from typing import Any

# ── File handler for security events ────────────────────────────
# Overridable via SECURITY_LOG_PATH (e.g. in CI, or any environment where
# /var/log isn't writable) — defaults to the same path production has
# always used, so real deployments are unaffected.
_SECURITY_LOG_PATH = os.environ.get("SECURITY_LOG_PATH", "/var/log/fim-security.log")

_security_logger = logging.getLogger("fim.security")
_security_logger.setLevel(logging.DEBUG)
# Also propagate to root logger (journald / uvicorn)
_security_logger.propagate = True

try:
    _security_file_handler = logging.handlers.RotatingFileHandler(
        _SECURITY_LOG_PATH,
        maxBytes=100_000_000,   # 100 MB
        backupCount=10,
        mode='a',
        encoding='utf-8',
    )
    _security_file_handler.setFormatter(logging.Formatter('%(message)s'))
    _security_logger.addHandler(_security_file_handler)
except OSError as e:
    # Don't let a missing/unwritable log path crash the whole app at import
    # time — this is a module-level side effect that runs the moment
    # anything imports app.core.security_logger. Fall back to the root
    # logger only (still visible in console/journald), and continue.
    logging.getLogger(__name__).warning(
        "Could not open security log file %s (%s) — security events will "
        "only go to the standard logger, not %s. Set SECURITY_LOG_PATH to "
        "override the path.", _SECURITY_LOG_PATH, e, _SECURITY_LOG_PATH,
    )


def security_log(event: str, level: str = "INFO", **fields: Any) -> None:
    """
    Write a structured security event.

    Args:
        event  : event name e.g. 'login_failed', 'csrf_blocked', 'role_changed'
        level  : DEBUG | INFO | WARNING | ERROR | CRITICAL
        **fields: arbitrary key-value pairs included in the JSON entry
    """
    entry = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "event":     event,
        "level":     level.upper(),
        **fields,
    }
    log_line = json.dumps(entry, default=str)

    log_fn = getattr(_security_logger, level.lower(), _security_logger.info)
    log_fn(log_line)


# ── Convenience wrappers ─────────────────────────────────────────

def log_login_failed(username: str, ip: str,
                     reason: str = "invalid_password", **kw) -> None:
    security_log("login_failed", level="WARNING",
                 username=username, ip=ip, reason=reason, **kw)


def log_login_success(username: str, ip: str,
                      user_agent: str = "", session_id: str = "", **kw) -> None:
    security_log("login_success", level="INFO",
                 username=username, ip=ip,
                 user_agent=user_agent, session_id=session_id, **kw)


def log_unauthorized(path: str, method: str, ip: str,
                     reason: str = "", **kw) -> None:
    security_log("unauthorized_access", level="WARNING",
                 path=path, method=method, ip=ip, reason=reason, **kw)


def log_forbidden(path: str, method: str, ip: str,
                  user_id: str = "", reason: str = "", **kw) -> None:
    security_log("forbidden_access", level="WARNING",
                 path=path, method=method, ip=ip,
                 user_id=user_id, reason=reason, **kw)


def log_password_change(user_id: str, changed_by: str, ip: str, **kw) -> None:
    security_log("password_changed", level="INFO",
                 user_id=user_id, changed_by=changed_by, ip=ip, **kw)


def log_role_change(target_user_id: str, new_role: str,
                    changed_by: str, ip: str, **kw) -> None:
    security_log("role_changed", level="WARNING",
                 target_user_id=target_user_id, new_role=new_role,
                 changed_by=changed_by, ip=ip, **kw)


def log_rate_limit_hit(path: str, ip: str, **kw) -> None:
    security_log("rate_limit_hit", level="WARNING",
                 path=path, ip=ip, **kw)
