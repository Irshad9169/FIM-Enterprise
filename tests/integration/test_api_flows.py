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
from sqlalchemy import text, select

from app.core.security import create_access_token, get_password_hash, SECRET_KEY, ALGORITHM
from app.models.models import Agent, Baseline, User, Alert

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


# ── Scan pause/resume ────────────────────────────────────────────────────────

async def test_pause_scan_flag_reaches_next_heartbeat(client, db_session):
    """
    pause-scan sets a desired-state flag on the Agent row; the agent's own
    heartbeat call is how it actually learns about it (see
    agent/fim_agent.py's run_daemon, which reads scan_pause_requested back
    from the heartbeat response every cycle).
    """
    admin = await _create_user(db_session, role="admin", username="admin3")
    agent = Agent(id=uuid.uuid4(), hostname="test-agent-06", status="online")
    db_session.add(agent)
    await db_session.commit()

    pause_resp = await client.post(
        f"/api/v1/agents/{agent.id}/pause-scan",
        headers=await _auth_headers(db_session, admin),
    )
    assert pause_resp.status_code == 200

    hb_resp = await client.post(
        "/api/v1/agents/heartbeat",
        json={"agent_id": str(agent.id), "hostname": agent.hostname},
        headers={"X-API-Key": "test-agent-06-key"},
    )
    assert hb_resp.status_code == 200
    assert hb_resp.json()["scan_pause_requested"] is True


async def test_resume_scan_clears_flag_and_queues_immediate_scan(client, db_session):
    """
    resume-scan must both clear the pause flag AND queue an on-demand scan
    (reusing the existing fim.scan_requests channel trigger_agent_scan uses)
    so the agent resumes on its very next heartbeat rather than waiting for
    the next scheduled interval (up to scan_interval, e.g. an hour).
    """
    admin = await _create_user(db_session, role="admin", username="admin4")
    agent = Agent(id=uuid.uuid4(), hostname="test-agent-07", status="online")
    db_session.add(agent)
    await db_session.commit()

    await client.post(
        f"/api/v1/agents/{agent.id}/pause-scan",
        headers=await _auth_headers(db_session, admin),
    )
    resume_resp = await client.post(
        f"/api/v1/agents/{agent.id}/resume-scan",
        headers=await _auth_headers(db_session, admin),
    )
    assert resume_resp.status_code == 200

    hb_resp = await client.post(
        "/api/v1/agents/heartbeat",
        json={"agent_id": str(agent.id), "hostname": agent.hostname},
        headers={"X-API-Key": "test-agent-07-key"},
    )
    body = hb_resp.json()
    assert body["scan_pause_requested"] is False
    assert body["scan_required"] is True


async def test_trainee_cannot_pause_scan(client, db_session):
    """Matches the pattern in test_trainee_cannot_approve_baseline — pause/resume are analyst_plus, not any authenticated user."""
    trainee = await _create_user(db_session, role="trainee", username="trainee2")
    agent = Agent(id=uuid.uuid4(), hostname="test-agent-08", status="online")
    db_session.add(agent)
    await db_session.commit()

    resp = await client.post(
        f"/api/v1/agents/{agent.id}/pause-scan",
        headers=await _auth_headers(db_session, trainee),
    )

    assert resp.status_code == 403


async def test_heartbeat_persists_reported_scan_progress(client, db_session):
    """The agent reports scan_status/scan_progress every heartbeat, decoupled from scan completion — confirm it lands on the Agent row."""
    agent = Agent(id=uuid.uuid4(), hostname="test-agent-09", status="online")
    db_session.add(agent)
    await db_session.commit()

    resp = await client.post(
        "/api/v1/agents/heartbeat",
        json={
            "agent_id": str(agent.id), "hostname": agent.hostname,
            "scan_status": "running",
            "scan_progress": {"processed": 42, "total": 100},
        },
        headers={"X-API-Key": "test-agent-09-key"},
    )
    assert resp.status_code == 200

    await db_session.refresh(agent)
    assert agent.scan_status == "running"
    assert agent.scan_progress_processed == 42
    assert agent.scan_progress_total == 100


# ── Change detection dedup — reviewed state shouldn't re-alert ─────────────

async def test_closed_alert_does_not_rebounce_for_the_same_reviewed_value(client, db_session):
    """
    Real bug found live this session: ChangeDetector always diffs against
    the (unchanged) approved baseline, never the previous scan, so a file
    that settled into a new, already-reviewed value kept generating a
    fresh alert on every single scan forever -- the old dedup only
    checked for a currently-OPEN alert on (path, type), so the moment an
    analyst closed it (acknowledged/resolved/false_positive), the very
    next scan (still seeing current != stale baseline) created a
    brand-new alert for the identical value. The only fix was manually
    re-baselining the whole host, which doesn't scale past a handful of
    servers. Now dedup checks ANY alert ever created for this exact
    (path, type, hash), open or already closed.
    """
    from app.services.change_detector import ChangeDetector

    agent = Agent(id=uuid.uuid4(), hostname="test-agent-10", status="online")
    db_session.add(agent)
    await db_session.commit()

    baseline_data = {"files": [{
        "path": "/etc/shadow", "hash": "original",
        "permissions": "600", "owner": "root", "group": "root", "size": 100,
    }]}
    baseline = Baseline(
        id=uuid.uuid4(), agent_id=agent.id, baseline_name="b-reviewed-state",
        baseline_data=baseline_data, file_count=1, total_size_bytes=100,
        checksum=ChangeDetector.compute_baseline_checksum(baseline_data),
        is_active=True, status="approved",
    )
    db_session.add(baseline)
    await db_session.commit()

    async def submit(file_hash: str):
        return await client.post(
            "/api/v1/scans/submit",
            json={
                "agent_id": str(agent.id),
                "timestamp": datetime.utcnow().isoformat() + "Z",
                "files": [{
                    "path": "/etc/shadow", "hash": file_hash,
                    "permissions": "600", "owner": "root", "group": "root", "size": 100,
                }],
                "total_files": 1,
            },
            headers={"X-API-Key": "test-agent-10-key"},
        )

    # First scan: hash differs from baseline -- a real, new alert.
    resp1 = await submit("changed-v1")
    assert resp1.json()["change_detection"]["alerts_created"] == 1

    # Close that alert out, same as an analyst reviewing and clearing it.
    result = await db_session.execute(
        select(Alert).where(Alert.agent_id == agent.id, Alert.file_path == "/etc/shadow")
    )
    alert = result.scalar_one()
    alert.status = "acknowledged"
    await db_session.commit()

    # Second scan: SAME hash as before -- nothing genuinely changed since
    # it was reviewed. Must NOT create a new alert, even though it still
    # differs from the (unchanged) baseline.
    resp2 = await submit("changed-v1")
    body2 = resp2.json()["change_detection"]
    assert body2["alerts_created"] == 0
    assert body2["skipped_duplicates"] == 1

    # Third scan: a genuinely new hash -- must still create a fresh alert.
    resp3 = await submit("changed-v2")
    assert resp3.json()["change_detection"]["alerts_created"] == 1


async def test_closed_deletion_alert_does_not_rebounce_while_still_deleted(client, db_session):
    """
    Deletion alerts had the same disease as modified/created ones (see
    test_closed_alert_does_not_rebounce_for_the_same_reviewed_value) but
    needed a different fingerprint since there's no content hash for
    "missing". Dedup now checks whether the most recent alert for a path
    was ALSO a deletion -- if so, it's the same ongoing "still deleted"
    state already reviewed, not a new event.
    """
    from app.services.change_detector import ChangeDetector

    agent = Agent(id=uuid.uuid4(), hostname="test-agent-11", status="online")
    db_session.add(agent)
    await db_session.commit()

    baseline_data = {"files": [{
        "path": "/etc/important-file", "hash": "original",
        "permissions": "600", "owner": "root", "group": "root", "size": 100,
    }]}
    baseline = Baseline(
        id=uuid.uuid4(), agent_id=agent.id, baseline_name="b-deletion-state",
        baseline_data=baseline_data, file_count=1, total_size_bytes=100,
        checksum=ChangeDetector.compute_baseline_checksum(baseline_data),
        is_active=True, status="approved",
    )
    db_session.add(baseline)
    await db_session.commit()

    async def submit_files(files: list):
        return await client.post(
            "/api/v1/scans/submit",
            json={
                "agent_id": str(agent.id),
                "timestamp": datetime.utcnow().isoformat() + "Z",
                "files": files,
                "total_files": len(files),
            },
            headers={"X-API-Key": "test-agent-11-key"},
        )

    # First scan: file is missing entirely -- a real, new deletion alert.
    resp1 = await submit_files([])
    assert resp1.json()["change_detection"]["alerts_created"] == 1

    # Close that alert out, same as an analyst reviewing and clearing it.
    result = await db_session.execute(
        select(Alert).where(Alert.agent_id == agent.id, Alert.file_path == "/etc/important-file")
    )
    alert = result.scalar_one()
    alert.status = "resolved"
    await db_session.commit()

    # Second scan: STILL missing -- nothing new happened since it was
    # reviewed. Must NOT create a new alert.
    resp2 = await submit_files([])
    body2 = resp2.json()["change_detection"]
    assert body2["alerts_created"] == 0
    assert body2["skipped_duplicates"] == 1

    # Third scan: the file reappears with different content (a genuinely
    # new state) -- a fresh 'modified' alert, breaking the deletion chain.
    resp3 = await submit_files([{
        "path": "/etc/important-file", "hash": "came-back-different",
        "permissions": "600", "owner": "root", "group": "root", "size": 100,
    }])
    assert resp3.json()["change_detection"]["alerts_created"] == 1

    # Fourth scan: deleted again -- this is a genuinely NEW deletion event
    # (the most recent alert for this path is now 'file_modified', not
    # 'file_deleted'), so it must alert again, not be deduped.
    resp4 = await submit_files([])
    assert resp4.json()["change_detection"]["alerts_created"] == 1
