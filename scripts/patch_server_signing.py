#!/usr/bin/env python3
"""
Patch scans.py to verify HMAC-SHA256 signature on scan submissions.
Run: python3 /opt/fim/patch_server_signing.py
"""

SCANS_PATH = "/opt/fim/app/api/scans.py"

with open(SCANS_PATH) as f:
    code = f.read()

# ── 1. Add imports ────────────────────────────────────────────────────────

old_imports = '''from fastapi import APIRouter, Depends, HTTPException, Query
from datetime import datetime, timezone
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, desc, text
from pydantic import BaseModel
from typing import List, Optional, Dict
import uuid
import logging
from app.core.database import get_db
from app.models.models import Agent, Scan
from app.services.change_detector import ChangeDetector'''

new_imports = '''from fastapi import APIRouter, Depends, HTTPException, Query, Request
from datetime import datetime, timezone
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, desc, text
from pydantic import BaseModel
from typing import List, Optional, Dict
import uuid
import hmac
import hashlib
import json
import logging
from app.core.database import get_db
from app.models.models import Agent, Scan
from app.services.change_detector import ChangeDetector'''

if old_imports in code:
    code = code.replace(old_imports, new_imports)
    print("Updated imports")
else:
    print("WARNING: Could not find import block — manually add: Request, hmac, hashlib, json")

# ── 2. Replace submit_scan to add signature verification ──────────────────

old_submit = '''@router.post("/submit")
async def submit_scan(request: ScanSubmitRequest, db: AsyncSession = Depends(get_db)):
    # ... (Keep existing submit logic logic, it works fine) ...
    # Re-pasting the submit logic for completeness
    try:
        agent_uuid = uuid.UUID(request.agent_id)
    except ValueError:
        raise HTTPException(400, "Invalid agent ID")
    result = await db.execute(select(Agent).where(Agent.id == agent_uuid))
    agent = result.scalar_one_or_none()
    if not agent: raise HTTPException(404, "Agent not found")'''

new_submit = '''@router.post("/submit")
async def submit_scan(
    raw_request: Request,
    db: AsyncSession = Depends(get_db)
):
    """
    Accept scan results from agents.
    Verifies HMAC-SHA256 signature if X-Scan-Signature header is present.
    Uses the agent's API key (from X-API-Key header) as the shared secret.
    """
    # ── Parse body ────────────────────────────────────────────────────
    try:
        raw_body = await raw_request.body()
        body = json.loads(raw_body)
        request = ScanSubmitRequest(**body)
    except Exception as e:
        raise HTTPException(400, f"Invalid request body: {e}")

    # ── Verify HMAC signature if present ──────────────────────────────
    signature = raw_request.headers.get("x-scan-signature", "")
    api_key = raw_request.headers.get("x-api-key", "")

    if signature:
        # Signature provided — MUST verify
        if not api_key:
            logger.warning(f"Scan submission with signature but no API key from {raw_request.client.host}")
            raise HTTPException(403, "API key required for signed submissions")

        # Recompute HMAC from canonical JSON
        try:
            payload = json.loads(raw_body)
            canonical = json.dumps(payload, sort_keys=True, separators=(',', ':'))
            expected = hmac.new(
                api_key.encode('utf-8'),
                canonical.encode('utf-8'),
                hashlib.sha256
            ).hexdigest()
        except Exception:
            raise HTTPException(400, "Failed to verify signature")

        received = signature.replace("hmac-sha256=", "")
        if not hmac.compare_digest(received, expected):
            logger.error(
                f"SCAN SIGNATURE MISMATCH — agent_id={request.agent_id} "
                f"ip={raw_request.client.host} — POSSIBLE TAMPERING"
            )
            raise HTTPException(
                403,
                "Scan signature verification failed — payload may have been tampered"
            )
        logger.info(f"Scan signature verified OK for agent {request.agent_id}")
    else:
        # No signature — log warning but allow (backward compatibility)
        logger.warning(
            f"Scan submission WITHOUT signature from agent {request.agent_id} "
            f"ip={raw_request.client.host} — consider upgrading agent"
        )

    # ── Process scan (existing logic) ─────────────────────────────────
    try:
        agent_uuid = uuid.UUID(request.agent_id)
    except ValueError:
        raise HTTPException(400, "Invalid agent ID")
    result = await db.execute(select(Agent).where(Agent.id == agent_uuid))
    agent = result.scalar_one_or_none()
    if not agent: raise HTTPException(404, "Agent not found")'''

if old_submit in code:
    code = code.replace(old_submit, new_submit)
    print("Patched submit_scan with signature verification")
else:
    print("WARNING: Could not find submit_scan — check manually")

with open(SCANS_PATH, 'w') as f:
    f.write(code)

print("\nDone! Server will now:")
print("  - Verify signature if X-Scan-Signature header is present")
print("  - Reject with 403 if signature doesn't match (tampering detected)")
print("  - Warn but allow if no signature (backward compatibility)")
print("\nRestart: systemctl restart fim-backend")
