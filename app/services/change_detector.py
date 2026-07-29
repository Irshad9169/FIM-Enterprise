"""
Change Detection Service - The FIM Brain
Compares scans against baselines and generates alerts with Whitelisting

Security features:
  - Baseline integrity verification: Before comparing against a baseline,
    the stored checksum is verified against a freshly computed SHA-256 hash
    of the baseline_data. If they don't match, the baseline is flagged as
    tampered/corrupted and the scan is rejected. This prevents a compromised
    database row from silently affecting change detection.
"""
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, and_, desc
from typing import List, Dict, Tuple, Set, Optional, Dict, List, Optional, Set
import logging
import uuid
import hashlib
import json
import re
import fnmatch
from datetime import datetime

from app.models.models import Scan, Baseline, Alert, WhitelistRule

logger = logging.getLogger(__name__)

GENESIS_HASH = "0" * 64  # matches fim.alerts.prev_hash / fim.audit_logs.prev_hash default


class BaselineIntegrityError(Exception):
    """Raised when a baseline fails integrity verification."""
    pass


class ChangeDetector:
    """Compares scans against baselines and generates alerts"""

    # ── Baseline Integrity ────────────────────────────────────────────────

    @staticmethod
    def compute_baseline_checksum(baseline_data: dict) -> str:
        """
        Compute SHA-256 checksum of baseline_data for integrity verification.
        Uses deterministic JSON serialization (sorted keys, no whitespace variance).
        """
        data_str = json.dumps(baseline_data, sort_keys=True, separators=(',', ':'))
        return hashlib.sha256(data_str.encode('utf-8')).hexdigest()

    @staticmethod
    def verify_baseline_integrity(baseline) -> bool:
        """
        Verify that the baseline's stored checksum matches the actual
        baseline_data content. Returns True if valid, False if tampered.

        If the baseline has no checksum (legacy baselines created before
        this feature), we log a warning but allow it to pass — the admin
        should re-approve these baselines to generate a checksum.
        """
        if not baseline.checksum:
            logger.warning(
                f"Baseline {baseline.id} has no stored checksum — "
                f"integrity cannot be verified. "
                f"Re-approve this baseline to generate a checksum."
            )
            return True  # Allow legacy baselines without checksum

        if not baseline.baseline_data:
            logger.error(f"Baseline {baseline.id} has checksum but no data — corrupted!")
            return False

        computed = ChangeDetector.compute_baseline_checksum(baseline.baseline_data)

        if computed != baseline.checksum:
            logger.error(
                f"BASELINE INTEGRITY FAILURE — baseline {baseline.id} "
                f"agent={baseline.agent_id}: "
                f"stored checksum={baseline.checksum[:16]}... "
                f"computed checksum={computed[:16]}... "
                f"DATA MAY BE TAMPERED!"
            )
            return False

        logger.debug(f"Baseline {baseline.id} integrity verified OK")
        return True

    # ── Alert Hash Chain ──────────────────────────────────────────────────

    @staticmethod
    async def _chain_alert_hashes(db: AsyncSession, evidence_fields: Dict) -> Tuple[str, str]:
        """
        Compute (entry_hash, prev_hash) for a new fim.alerts row, chaining
        from the most recent existing row — same pattern as
        AuditService._chain_hashes. A DB trigger (see migration
        0002_alert_hash_chain) blocks changing these "evidence" fields (or
        entry_hash/prev_hash themselves) on UPDATE, and blocks DELETE
        entirely; the ordinary analyst workflow columns (status,
        assigned_to, resolution_notes, acknowledged_at/by, resolved_at)
        stay updatable as normal.
        Same concurrency caveat as AuditService: no explicit serialization,
        so concurrent inserts can fork the chain rather than guarantee
        strict linearity — acceptable for now, matches the existing
        audit-log chain's design.
        """
        result = await db.execute(
            select(Alert.entry_hash).order_by(desc(Alert.detected_at), desc(Alert.id)).limit(1)
        )
        prev_hash = result.scalar_one_or_none() or GENESIS_HASH
        canonical = json.dumps(evidence_fields, sort_keys=True, separators=(",", ":"), default=str)
        entry_hash = hashlib.sha256((canonical + prev_hash).encode("utf-8")).hexdigest()
        return entry_hash, prev_hash

    # ── Main Scan Processing ──────────────────────────────────────────────

    @staticmethod
    async def process_scan(scan_id: uuid.UUID, db: AsyncSession) -> Dict:
        """Process a new scan and detect changes"""
        result = await db.execute(select(Scan).where(Scan.id == scan_id))
        scan = result.scalar_one_or_none()

        if not scan or not scan.scan_data:
            return {'error': 'Scan not found or no data'}

        result = await db.execute(
            select(Baseline)
            .where(Baseline.agent_id == scan.agent_id)
            .where(Baseline.is_active == True)
            .limit(1)
        )
        baseline = result.scalar_one_or_none()

        # 1. AUTO-CREATE BASELINE IF MISSING
        if not baseline:
            data_str = json.dumps(scan.scan_data, sort_keys=True, separators=(',', ':'))
            checksum = hashlib.sha256(data_str.encode('utf-8')).hexdigest()
            new_baseline = Baseline(
                id=uuid.uuid4(),
                agent_id=scan.agent_id,
                baseline_name=f"Initial Baseline - {datetime.now().strftime('%Y-%m-%d %H:%M')}",
                baseline_data=scan.scan_data,
                file_count=scan.files_scanned,
                total_size_bytes=0,
                checksum=checksum,
                is_active=True,
                status='pending',
                created_at=datetime.utcnow()
            )
            db.add(new_baseline)
            logger.info(
                f"Created initial baseline for agent {scan.agent_id} "
                f"with {scan.files_scanned} files, checksum={checksum[:16]}..."
            )
            return {'status': 'baseline_created', 'message': 'Initial baseline created'}

        # 2. VERIFY BASELINE INTEGRITY BEFORE COMPARISON
        if not ChangeDetector.verify_baseline_integrity(baseline):
            # Baseline is tampered or corrupted — do NOT compare
            # Mark it as compromised in DB
            baseline.status = 'integrity_failed'
            baseline.is_active = False
            await db.commit()

            logger.critical(
                f"Baseline {baseline.id} FAILED integrity check — "
                f"deactivated. Agent {scan.agent_id} scans will create "
                f"a new baseline on next run. INVESTIGATE IMMEDIATELY."
            )

            # Create a critical alert for the integrity failure
            try:
                detected_at = datetime.utcnow()
                previous_state = {"baseline_id": str(baseline.id), "stored_checksum": baseline.checksum}
                current_state = {"computed_checksum": ChangeDetector.compute_baseline_checksum(baseline.baseline_data)}
                change_details = {
                    'change_type': 'baseline_integrity_failure',
                    'detected_at': detected_at.isoformat(),
                    'message': 'Baseline data does not match stored checksum. Possible tampering.'
                }
                entry_hash, prev_hash = await ChangeDetector._chain_alert_hashes(db, {
                    "agent_id": str(scan.agent_id),
                    "file_path": "SYSTEM:baseline_integrity",
                    "alert_type": "baseline_tampered",
                    "severity": "critical",
                    "previous_state": previous_state,
                    "current_state": current_state,
                    "change_details": change_details,
                    "detected_at": detected_at.isoformat(),
                })
                integrity_alert = Alert(
                    id=uuid.uuid4(),
                    agent_id=scan.agent_id,
                    file_path="SYSTEM:baseline_integrity",
                    alert_type="baseline_tampered",
                    severity="critical",
                    status='open',
                    previous_state=previous_state,
                    current_state=current_state,
                    change_details=change_details,
                    detected_at=detected_at,
                    created_at=detected_at,
                    entry_hash=entry_hash,
                    prev_hash=prev_hash,
                )
                db.add(integrity_alert)
                await db.commit()
            except Exception as e:
                logger.error(f"Failed to create integrity alert: {e}")

            return {
                'status': 'integrity_error',
                'error': 'Baseline integrity verification failed — possible tampering detected',
                'baseline_id': str(baseline.id),
            }

        # 3. COMPARE FILES
        changes = ChangeDetector._compare_files(
            baseline.baseline_data.get('files', []),
            scan.scan_data.get('files', [])
        )

        # 4. FETCH WHITELIST RULES (Exclusions)
        # Fetch global rules AND agent-specific rules for this agent
        whitelist_query = await db.execute(
            select(WhitelistRule).where(
                and_(
                    WhitelistRule.is_active == True,
                    (WhitelistRule.scope == 'global') | (WhitelistRule.agent_id == scan.agent_id)
                )
            )
        )
        whitelist_rules = whitelist_query.scalars().all()

        # 5. FETCH EXISTING OPEN ALERTS (Deduplication)
        open_alerts_query = await db.execute(
            select(Alert.file_path, Alert.alert_type)
            .where(and_(Alert.agent_id == scan.agent_id, Alert.status == 'open'))
        )
        existing_alerts: Set[tuple] = {
            (row.file_path, row.alert_type) for row in open_alerts_query.fetchall()
        }

        # 6. CREATE ALERTS (Filtered by Whitelist and Duplicates)
        alerts_created = 0
        whitelisted_count = 0
        skipped_duplicates = 0

        for change in changes:
            alert_type = f"file_{change['type']}"
            path = change['path']

            # Check if duplicated
            if (path, alert_type) in existing_alerts:
                skipped_duplicates += 1
                continue

            # Check if whitelisted (EXCLUSIONS)
            is_excluded = False
            for rule in whitelist_rules:
                if ChangeDetector._check_whitelist_match(path, rule):
                    is_excluded = True
                    # Increment match count for rule
                    rule.match_count = (rule.match_count or 0) + 1
                    rule.last_matched_at = datetime.utcnow()
                    break

            if is_excluded:
                whitelisted_count += 1
                continue

            try:
                await ChangeDetector._create_alert(scan.agent_id, change, db)
                alerts_created += 1
            except Exception as e:
                logger.error(f"Failed to create alert: {e}")

        return {
            'status': 'completed',
            'baseline_verified': True,
            'changes_detected': len(changes),
            'alerts_created': alerts_created,
            'whitelisted_ignored': whitelisted_count,
            'skipped_duplicates': skipped_duplicates
        }

    # ── Whitelist Matching ────────────────────────────────────────────────

    @staticmethod
    def _check_whitelist_match(path: str, rule: WhitelistRule) -> bool:
        """Check if a path matches a whitelist rule"""
        try:
            if rule.rule_type == 'path':
                return path == rule.match_value
            elif rule.rule_type == 'glob':
                return fnmatch.fnmatch(path, rule.match_value)
            elif rule.rule_type == 'regex':
                return bool(re.match(rule.match_value, path))
        except Exception as e:
            logger.error(f"Error matching rule {rule.id}: {e}")
        return False

    # ── File Comparison ───────────────────────────────────────────────────

    @staticmethod
    def _compare_files(baseline_files: List[Dict], scan_files: List[Dict]) -> List[Dict]:
        baseline_map = {f['path']: f for f in baseline_files}
        scan_map = {f['path']: f for f in scan_files}
        changes = []

        for path, scan_file in scan_map.items():
            baseline_file = baseline_map.get(path)
            if not baseline_file:
                changes.append({
                    'type': 'created', 'path': path,
                    'severity': ChangeDetector._severity_for_new_file(path),
                    'current_state': scan_file, 'previous_state': None
                })
            elif ChangeDetector._file_changed(baseline_file, scan_file):
                changes.append({
                    'type': 'modified', 'path': path, 'severity': 'medium',
                    'current_state': scan_file, 'previous_state': baseline_file,
                    'changes': ChangeDetector._get_change_details(baseline_file, scan_file)
                })

        for path, baseline_file in baseline_map.items():
            if path not in scan_map:
                changes.append({
                    'type': 'deleted', 'path': path, 'severity': 'high',
                    'current_state': None, 'previous_state': baseline_file
                })
        return changes

    @staticmethod
    def _file_changed(baseline: Dict, current: Dict) -> bool:
        return (
            baseline.get('hash') != current.get('hash') or
            baseline.get('permissions') != current.get('permissions') or
            baseline.get('owner') != current.get('owner') or
            baseline.get('group') != current.get('group') or
            baseline.get('size') != current.get('size')
        )

    @staticmethod
    def _get_change_details(baseline: Dict, current: Dict) -> Dict:
        details = {}
        if baseline.get('hash') != current.get('hash'):
            details['hash'] = {'old': baseline.get('hash'), 'new': current.get('hash')}
        if baseline.get('size') != current.get('size'):
            details['size'] = {'old': baseline.get('size'), 'new': current.get('size')}
        if baseline.get('permissions') != current.get('permissions'):
            details['permissions'] = {'old': baseline.get('permissions'), 'new': current.get('permissions')}
        if baseline.get('owner') != current.get('owner'):
            details['owner'] = {'old': baseline.get('owner'), 'new': current.get('owner')}
        if baseline.get('group') != current.get('group'):
            details['group'] = {'old': baseline.get('group'), 'new': current.get('group')}
        return details

    @staticmethod
    def _severity_for_new_file(path: str) -> str:
        if path.startswith(('/etc', '/bin', '/sbin', '/usr/bin', '/usr/sbin')):
            return 'high'
        return 'medium'

    @staticmethod
    async def _create_alert(agent_id: uuid.UUID, change: Dict, db: AsyncSession):
        detected_at = datetime.utcnow()
        alert_type = f"file_{change['type']}"
        previous_state = change.get('previous_state')
        current_state = change.get('current_state')
        change_details = {
            'change_type': change['type'],
            'detected_at': detected_at.isoformat(),
            'changes': change.get('changes', {})
        }
        # Populated agent-side (fim_agent.py's _correlate_auditd) only for a
        # curated critical-path list, and only when the file's content
        # actually changed — null for everything else. Lives in
        # current_state (the raw per-file scan dict) since the agent
        # payload already carries arbitrary fields through untouched.
        audit_uid = (current_state or {}).get('audit_uid')
        audit_process = (current_state or {}).get('audit_process')
        audit_command = (current_state or {}).get('audit_command')

        entry_hash, prev_hash = await ChangeDetector._chain_alert_hashes(db, {
            "agent_id": str(agent_id),
            "file_path": change['path'],
            "alert_type": alert_type,
            "severity": change['severity'],
            "previous_state": previous_state,
            "current_state": current_state,
            "change_details": change_details,
            "detected_at": detected_at.isoformat(),
            "audit_uid": audit_uid,
            "audit_process": audit_process,
            "audit_command": audit_command,
        })
        alert = Alert(
            id=uuid.uuid4(),
            agent_id=agent_id,
            file_path=change['path'],
            alert_type=alert_type,
            severity=change['severity'],
            status='open',
            previous_state=previous_state,
            current_state=current_state,
            change_details=change_details,
            detected_at=detected_at,
            created_at=detected_at,
            entry_hash=entry_hash,
            prev_hash=prev_hash,
            audit_uid=audit_uid,
            audit_process=audit_process,
            audit_command=audit_command,
        )
        db.add(alert)
