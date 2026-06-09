"""
Baseline Version Control Service — GAP #21

Provides git-based immutable snapshots of approved baselines.
Every baseline approval triggers a snapshot commit.

Usage:
    from app.services.baseline_version_control import (
        snapshot_baseline, get_baseline_history
    )
    git_hash = await snapshot_baseline(db, baseline_id)
"""

import json
import logging
import os
import subprocess
import hashlib
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional, Set, Tuple

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger(__name__)

BASELINES_GIT_DIR = "/opt/fim/baselines-git"


def _git(args: List[str], cwd: str = BASELINES_GIT_DIR) -> Tuple[int, str]:
    """Run a git command and return (returncode, output)."""
    try:
        result = subprocess.run(
            ["git"] + args,
            cwd=cwd,
            capture_output=True,
            text=True,
            timeout=30,
        )
        return result.returncode, (result.stdout + result.stderr).strip()
    except Exception as e:
        return 1, str(e)


async def snapshot_baseline(db: AsyncSession,
                              baseline_id: str) -> Optional[str]:
    """
    GAP #21: Create a git snapshot of an approved baseline.

    Steps:
      1. Fetch full baseline data from DB
      2. Export to JSON file in the git repo
      3. git add + git commit
      4. Store commit hash back in fim.baselines.git_hash

    Returns: git commit hash, or None on failure
    """
    try:
        # Fetch baseline with agent info
        result = await db.execute(text("""
            SELECT
                b.id, b.agent_id, b.status, b.approved_at,
                b.approved_by, b.files_count, b.checksum,
                b.baseline_data, b.justification,
                a.hostname as agent_hostname
            FROM fim.baselines b
            JOIN fim.agents a ON b.agent_id = a.id
            WHERE b.id = :baseline_id
        """), {"baseline_id": baseline_id})
        baseline = result.fetchone()

        if not baseline:
            logger.error("GAP#21: Baseline %s not found", baseline_id)
            return None

        # Build snapshot document
        snapshot = {
            "baseline_id":   str(baseline.id),
            "agent_id":      str(baseline.agent_id),
            "agent_hostname": baseline.agent_hostname,
            "status":        baseline.status,
            "approved_at":   str(baseline.approved_at) if baseline.approved_at else None,
            "approved_by":   str(baseline.approved_by) if baseline.approved_by else None,
            "files_count":   baseline.files_count,
            "checksum":      baseline.checksum,
            "justification": baseline.justification,
            "snapshot_at":   datetime.now(timezone.utc).isoformat(),
            "snapshot_version": "1.0",
            # Include baseline data if available
            "baseline_data": baseline.baseline_data if baseline.baseline_data else None,
        }

        # Compute snapshot checksum
        snapshot_checksum = hashlib.sha256(
            json.dumps(snapshot, sort_keys=True, default=str).encode()
        ).hexdigest()
        snapshot["snapshot_checksum"] = snapshot_checksum

        # Build file path: <git-repo>/<agent-hostname>/<timestamp>_<id>.json
        agent_dir = Path(BASELINES_GIT_DIR) / _safe_dirname(baseline.agent_hostname)
        agent_dir.mkdir(parents=True, exist_ok=True)

        timestamp = datetime.now(timezone.utc).strftime("%Y-%m-%d_%H%M%S")
        filename = f"{timestamp}_{str(baseline.id)[:8]}.json"
        snapshot_path = agent_dir / filename

        # Write snapshot
        with open(snapshot_path, 'w') as f:
            json.dump(snapshot, f, indent=2, default=str)

        # Git operations
        rel_path = str(snapshot_path.relative_to(BASELINES_GIT_DIR))

        rc, out = _git(["add", rel_path])
        if rc != 0:
            logger.error("GAP#21: git add failed: %s", out)
            return None

        commit_msg = (
            f"Baseline snapshot: {baseline.agent_hostname}\n\n"
            f"Baseline ID : {baseline_id}\n"
            f"Files       : {baseline.files_count}\n"
            f"Checksum    : {baseline.checksum}\n"
            f"Approved by : {baseline.approved_by}\n"
            f"Snapshot SHA: {snapshot_checksum}"
        )
        rc, out = _git(["commit", "-m", commit_msg])
        if rc != 0 and "nothing to commit" not in out:
            logger.error("GAP#21: git commit failed: %s", out)
            return None

        # Get the commit hash
        rc, git_hash = _git(["rev-parse", "HEAD"])
        if rc != 0:
            logger.error("GAP#21: git rev-parse failed: %s", git_hash)
            return None

        git_hash = git_hash.strip()[:40]

        # Store hash + path back in DB
        await db.execute(text("""
            UPDATE fim.baselines
            SET git_hash     = :git_hash,
                snapshot_path = :snapshot_path
            WHERE id = :baseline_id
        """), {
            "git_hash":      git_hash,
            "snapshot_path": str(snapshot_path),
            "baseline_id":   baseline_id,
        })
        await db.commit()

        logger.info(
            "GAP#21: Baseline snapshot committed | agent=%s id=%s hash=%s",
            baseline.agent_hostname, baseline_id, git_hash[:8]
        )
        return git_hash

    except Exception as e:
        logger.error("GAP#21: Snapshot failed for %s: %s", baseline_id, e)
        return None


async def get_baseline_history(agent_hostname: str) -> List[Dict]:
    """
    Return full git log for a specific agent's baselines.
    Each entry = one approved baseline snapshot.
    """
    try:
        agent_dir = _safe_dirname(agent_hostname)
        rc, log_output = _git([
            "log",
            "--pretty=format:%H|%ai|%s",
            "--",
            f"{agent_dir}/"
        ])
        if rc != 0 or not log_output.strip():
            return []

        history = []
        for line in log_output.strip().splitlines():
            parts = line.split("|", 2)
            if len(parts) == 3:
                history.append({
                    "commit_hash": parts[0],
                    "committed_at": parts[1],
                    "message": parts[2],
                })
        return history

    except Exception as e:
        logger.error("GAP#21: History retrieval failed for %s: %s",
                     agent_hostname, e)
        return []


async def get_snapshot_content(git_hash: str,
                                 agent_hostname: str) -> Optional[dict]:
    """
    Retrieve the baseline JSON snapshot at a specific git commit.
    Used for forensic investigation.
    """
    try:
        agent_dir = _safe_dirname(agent_hostname)
        # List files at this commit
        rc, files = _git(["ls-tree", "--name-only", git_hash, f"{agent_dir}/"])
        if rc != 0 or not files.strip():
            return None

        # Get the most recent file at this commit
        snapshot_file = files.strip().splitlines()[-1]
        rc, content = _git(["show", f"{git_hash}:{snapshot_file}"])
        if rc != 0:
            return None

        return json.loads(content)

    except Exception as e:
        logger.error("GAP#21: Snapshot retrieval failed: %s", e)
        return None


async def snapshot_all_approved_baselines(db: AsyncSession) -> int:
    """
    One-time backfill: create snapshots for all existing approved
    baselines that don't have a git_hash yet.
    """
    result = await db.execute(text("""
        SELECT b.id
        FROM fim.baselines b
        WHERE b.status IN ('approved', 'active', 'superseded')
          AND b.git_hash IS NULL
        ORDER BY b.approved_at ASC NULLS LAST
        LIMIT 100
    """))
    baselines = result.fetchall()

    count = 0
    for row in baselines:
        git_hash = await snapshot_baseline(db, str(row.id))
        if git_hash:
            count += 1

    logger.info("GAP#21: Backfilled %d baseline snapshot(s)", count)
    return count


def _safe_dirname(hostname: str) -> str:
    """Convert hostname to safe directory name."""
    return "".join(c if c.isalnum() or c in ".-_" else "_" for c in hostname)
