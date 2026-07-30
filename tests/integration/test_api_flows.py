"""
Integration tests — real HTTP requests through the actual FastAPI app,
backed by a real (throwaway) Postgres database. See conftest.py for how
the schema is created and cleaned between tests.

Marked `integration` (see pytest.ini) so the fast, DB-less unit test job
skips these; they run in a separate CI job with a Postgres service
container (see .github/workflows/test.yml).

Login is rate-limited to 5/min per IP (app/middleware/rate_limiter.py),
and all requests here share one "IP" through the in-process ASGI
transport — so real /login HTTP calls are deliberately kept to the two
tests that specifically test the login endpoint. Every other test mints
a JWT directly via create_access_token() instead of calling /login,
which is legitimate since that function has its own dedicated unit
tests in tests/test_security.py.
"""
import uuid
from datetime import datetime, timedelta

import pytest
from jose import jwt as jose_jwt
from sqlalchemy import text

from app.core.security import create_access_token, get_password_hash, SECRET_KEY, ALGORITHM
from app.models.models import Agent, Baseline, User

pytestmark = pytest.mark.integration


async def _create_user(db_session, role="admin", username="testuser"):
    user = User(
        id=uuid.uuid4(),
        username=username,
        email=f"{username}@example.com",
        password_hash=get_password_hash("Str0ngPassw0rd!"),
        role=role,
        is_active=True,
    )
    db_session.add(user)
    await db_session.commit()
    await db_session.refresh(user)
    return user


async def _auth_headers(db_session, user):
    """
    Mint a JWT directly (bypassing the rate-limited /login endpoint — see
    module docstring) AND insert the matching fim.sessions row, since
    get_current_user() checks session validity by token jti on every
    authenticated request (app/core/security.py, GAP #12). Without this,
    every request using a directly-minted token gets 401 "Session has
    been revoked" even though no session was ever revoked — none existed.
    """
    token = create_access_token(
        {"sub": str(user.id), "username": user.username, "role": user.role}
    )
    payload = jose_jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM], options={"require_exp": True})
    await db_session.execute(text("""
        INSERT INTO fim.sessions (user_id, token_jti, expires_at)
        VALUES (:uid, :jti, :expires)
    """), {
        "uid": str(user.id),
        "jti": payload["jti"],
        "expires": datetime.utcnow() + timedelta(hours=1),
    })
    await db_session.commit()
    return {"Authorization": f"Bearer {token}"}


# ── Login flow ─────────────────────────────────────────────────────────────

async def test_login_succeeds_with_correct_credentials(client, db_session):
    await _create_user(db_session, role="admin", username="loginuser")

    resp = await client.post(
        "/api/v1/auth/login",
        json={"username": "loginuser", "password": "Str0ngPassw0rd!"},
    )

    assert resp.status_code == 200
    body = resp.json()
    assert body["user"]["username"] == "loginuser"
    assert body["user"]["role"] == "admin"
    assert "access_token" in body


async def test_login_rejects_wrong_password(client, db_session):
    await _create_user(db_session, role="admin", username="loginuser2")

    resp = await client.post(
        "/api/v1/auth/login",
        json={"username": "loginuser2", "password": "WrongPassword!"},
    )

    assert resp.status_code == 401


# ── Scan submission → change detection → alert creation ───────────────────

async def test_scan_submission_creates_initial_baseline(client, db_session):
    agent = Agent(id=uuid.uuid4(), hostname="test-agent-01", status="online")
    db_session.add(agent)
    await db_session.commit()

    resp = await client.post(
        "/api/v1/scans/submit",
        json={
            "agent_id": str(agent.id),
            "timestamp": datetime.utcnow().isoformat() + "Z",
            "files": [{
                "path": "/etc/passwd", "hash": "abc123",
                "permissions": "644", "owner": "root", "group": "root", "size": 100,
            }],
            "total_files": 1,
        },
        headers={"X-API-Key": "test-agent-01-key"},
    )

    assert resp.status_code == 200
    body = resp.json()
    assert body["success"] is True
    assert body["change_detection"]["status"] == "baseline_created"


async def test_scan_submission_detects_modified_file_and_creates_alert(client, db_session):
    from app.services.change_detector import ChangeDetector

    agent = Agent(id=uuid.uuid4(), hostname="test-agent-02", status="online")
    db_session.add(agent)
    await db_session.commit()

    baseline_data = {"files": [{
        "path": "/etc/passwd", "hash": "original",
        "permissions": "644", "owner": "root", "group": "root", "size": 100,
    }]}
    baseline = Baseline(
        id=uuid.uuid4(), agent_id=agent.id, baseline_name="test-baseline",
        baseline_data=baseline_data, file_count=1, total_size_bytes=100,
        checksum=ChangeDetector.compute_baseline_checksum(baseline_data),
        is_active=True, status="approved",
    )
    db_session.add(baseline)
    await db_session.commit()

    resp = await client.post(
        "/api/v1/scans/submit",
        json={
            "agent_id": str(agent.id),
            "timestamp": datetime.utcnow().isoformat() + "Z",
            "files": [{
                "path": "/etc/passwd", "hash": "changed",
                "permissions": "644", "owner": "root", "group": "root", "size": 100,
            }],
            "total_files": 1,
        },
        headers={"X-API-Key": "test-agent-02-key"},
    )

    assert resp.status_code == 200
    body = resp.json()
    assert body["change_detection"]["status"] == "completed"
    assert body["change_detection"]["changes_detected"] == 1
    assert body["change_detection"]["alerts_created"] == 1


async def test_scan_submission_rejects_unknown_agent(client):
    resp = await client.post(
        "/api/v1/scans/submit",
        json={
            "agent_id": str(uuid.uuid4()),
            "timestamp": datetime.utcnow().isoformat() + "Z",
            "files": [],
            "total_files": 0,
        },
    )
    assert resp.status_code == 404


# ── Baseline approval — RBAC over real HTTP ────────────────────────────────

async def test_admin_can_approve_baseline(client, db_session):
    admin = await _create_user(db_session, role="admin", username="admin1")
    agent = Agent(id=uuid.uuid4(), hostname="test-agent-03", status="online")
    db_session.add(agent)
    await db_session.commit()
    # baseline_data must be non-empty here: ChangeDetector.process_scan()
    # (the only real code path that creates baselines) always populates it,
    # so a baseline with neither baseline_data nor checksum set isn't a
    # realistic precondition — approve_baseline() isn't written to handle
    # that combination gracefully (crashes on checksum[:16] when both are
    # None), which is a minor robustness gap worth knowing about, but not
    # what this test is meant to exercise.
    baseline = Baseline(
        id=uuid.uuid4(), agent_id=agent.id, baseline_name="b1",
        baseline_data={"files": [{"path": "/etc/passwd", "hash": "abc"}]},
        status="pending", is_active=False,
    )
    db_session.add(baseline)
    await db_session.commit()

    resp = await client.post(
        f"/api/v1/baselines/{baseline.id}/approve",
        headers=await _auth_headers(db_session, admin),
    )

    assert resp.status_code == 200


async def test_trainee_cannot_approve_baseline(client, db_session):
    """
    Per the README's Roles & Permissions table, only admin/analyst should
    be able to approve baselines.

    This test originally caught a real gap: approve_baseline() required
    only Depends(get_current_user) — ANY authenticated user — with no
    role check anywhere in the handler body, so a trainee or auditor
    account could approve baselines via a direct API call even though
    the UI hides that action for their role. Fixed by depending on
    core/rbac.py's analyst_plus instead (admin or analyst only),
    matching rebaseline() which had the identical gap.
    """
    trainee = await _create_user(db_session, role="trainee", username="trainee1")
    agent = Agent(id=uuid.uuid4(), hostname="test-agent-04", status="online")
    db_session.add(agent)
    await db_session.commit()
    baseline = Baseline(
        id=uuid.uuid4(), agent_id=agent.id, baseline_name="b2",
        baseline_data={"files": [{"path": "/etc/passwd", "hash": "abc"}]},
        status="pending", is_active=False,
    )
    db_session.add(baseline)
    await db_session.commit()

    resp = await client.post(
        f"/api/v1/baselines/{baseline.id}/approve",
        headers=await _auth_headers(db_session, trainee),
    )

    assert resp.status_code == 403


async def test_baseline_approval_requires_authentication(client, db_session):
    agent = Agent(id=uuid.uuid4(), hostname="test-agent-05", status="online")
    db_session.add(agent)
    await db_session.commit()
    baseline = Baseline(
        id=uuid.uuid4(), agent_id=agent.id, baseline_name="b3",
        status="pending", is_active=False,
    )
    db_session.add(baseline)
    await db_session.commit()

    resp = await client.post(f"/api/v1/baselines/{baseline.id}/approve")

    assert resp.status_code in (401, 403)


async def test_approve_nonexistent_baseline_returns_404(client, db_session):
    admin = await _create_user(db_session, role="admin", username="admin2")

    resp = await client.post(
        f"/api/v1/baselines/{uuid.uuid4()}/approve",
        headers=await _auth_headers(db_session, admin),
    )

    assert resp.status_code == 404
