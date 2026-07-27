"""
Unit tests for the two RBAC permission layers:
  - app/core/rbac.py         (admin_only, analyst_plus, require_role)
  - app/middleware/rbac.py   (require_permission + ROLE_PERMISSIONS matrix)

These call the dependency functions directly with a stub user, bypassing
FastAPI's Depends() injection entirely — the functions are plain Python
underneath, so this exercises the exact same authorization logic a real
request would hit, without needing a running app or a database.

This is the authorization matrix for the whole product: a regression here
means either wrongful denial or, worse, a privilege escalation.
"""
import pytest
from fastapi import HTTPException

from app.core import rbac as core_rbac
from app.middleware.rbac import require_permission, ROLE_PERMISSIONS


# ── app/core/rbac.py ───────────────────────────────────────────────────────

def test_admin_only_allows_admin(make_user):
    admin = make_user("admin")
    assert core_rbac.admin_only(admin) is admin


@pytest.mark.parametrize("role", ["analyst", "trainee", "auditor"])
def test_admin_only_rejects_non_admin(make_user, role):
    with pytest.raises(HTTPException) as exc_info:
        core_rbac.admin_only(make_user(role))
    assert exc_info.value.status_code == 403


@pytest.mark.parametrize("role", ["admin", "analyst"])
def test_analyst_plus_allows_admin_and_analyst(make_user, role):
    user = make_user(role)
    assert core_rbac.analyst_plus(user) is user


@pytest.mark.parametrize("role", ["trainee", "auditor"])
def test_analyst_plus_rejects_trainee_and_auditor(make_user, role):
    with pytest.raises(HTTPException) as exc_info:
        core_rbac.analyst_plus(make_user(role))
    assert exc_info.value.status_code == 403


def test_require_role_admin_bypasses_specific_role_check(make_user):
    # Admin is special-cased to pass any require_role() check regardless
    # of the specific role requested.
    checker = core_rbac.require_role("auditor")
    admin = make_user("admin")
    assert checker(admin) is admin


def test_require_role_allows_matching_role(make_user):
    checker = core_rbac.require_role("trainee")
    trainee = make_user("trainee")
    assert checker(trainee) is trainee


def test_require_role_rejects_non_matching_role(make_user):
    checker = core_rbac.require_role("trainee")
    with pytest.raises(HTTPException) as exc_info:
        checker(make_user("auditor"))
    assert exc_info.value.status_code == 403


# ── app/middleware/rbac.py — ROLE_PERMISSIONS matrix ────────────────────────

async def test_admin_has_every_permission(make_user):
    admin = make_user("admin")
    for permission in ROLE_PERMISSIONS["admin"]:
        checker = require_permission(permission)
        assert await checker(admin) is admin


async def test_analyst_cannot_manage_users(make_user):
    checker = require_permission("users_manage")
    with pytest.raises(HTTPException) as exc_info:
        await checker(make_user("analyst"))
    assert exc_info.value.status_code == 403


async def test_analyst_can_trigger_scans(make_user):
    checker = require_permission("scans_trigger")
    analyst = make_user("analyst")
    assert await checker(analyst) is analyst


async def test_trainee_cannot_trigger_scans(make_user):
    checker = require_permission("scans_trigger")
    with pytest.raises(HTTPException):
        await checker(make_user("trainee"))


async def test_trainee_can_acknowledge_alerts_but_not_manage_them(make_user):
    trainee = make_user("trainee")
    assert await require_permission("alerts_acknowledge")(trainee) is trainee
    with pytest.raises(HTTPException):
        await require_permission("alerts_manage")(trainee)


async def test_auditor_can_view_audit_logs_but_is_otherwise_read_only(make_user):
    auditor = make_user("auditor")
    assert await require_permission("audit_logs_view")(auditor) is auditor
    with pytest.raises(HTTPException):
        await require_permission("reports_submit")(auditor)
    with pytest.raises(HTTPException):
        await require_permission("baselines_approve")(auditor)


async def test_unknown_role_is_denied_every_permission(make_user):
    # A role that doesn't exist in ROLE_PERMISSIONS at all (e.g. a bad
    # migration, a typo'd role column) must fail closed, not open.
    stranger = make_user("some-future-role-that-does-not-exist")
    with pytest.raises(HTTPException) as exc_info:
        await require_permission("reports_generate")(stranger)
    assert exc_info.value.status_code == 403
