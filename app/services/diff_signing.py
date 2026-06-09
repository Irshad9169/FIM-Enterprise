"""
Baseline Diff Signing Service — GAP #23

Signs baseline diffs with HMAC-SHA256 using the application SECRET_KEY.
Any tampering with the diff between generation and approval is detected
by signature verification failure.

Usage:
    from app.services.diff_signing import sign_diff, verify_diff_signature

    # On diff generation:
    signature = sign_diff(diff_data)

    # On diff retrieval (before showing to approver):
    is_valid = verify_diff_signature(diff_data, stored_signature)
    if not is_valid:
        raise HTTPException(422, "Diff signature invalid — possible tampering")
"""

import hashlib
import hmac
import json
import logging
from datetime import datetime, timezone
from typing import Any

logger = logging.getLogger(__name__)


def _get_secret_key() -> bytes:
    """Get SECRET_KEY from app settings."""
    try:
        from app.core.config import settings
        key = settings.secret_key
        if isinstance(key, str):
            key = key.encode()
        return key
    except Exception as e:
        logger.error("GAP#23: Cannot load SECRET_KEY: %s", e)
        raise RuntimeError("SECRET_KEY not available for diff signing") from e


def _canonical_diff(diff_data: Any) -> bytes:
    """
    Convert diff to canonical bytes for signing.
    Uses sorted keys to ensure deterministic serialization.
    """
    if isinstance(diff_data, (dict, list)):
        return json.dumps(diff_data, sort_keys=True,
                          separators=(',', ':'), default=str).encode()
    if isinstance(diff_data, str):
        return diff_data.encode()
    return str(diff_data).encode()


def sign_diff(diff_data: Any, baseline_id: str = "") -> str:
    """
    GAP #23: Compute HMAC-SHA256 signature for a baseline diff.

    Args:
        diff_data  : the diff content (dict, list, or str)
        baseline_id: optional baseline ID to bind signature to specific baseline

    Returns:
        64-character hex HMAC-SHA256 signature
    """
    secret_key = _get_secret_key()
    canonical  = _canonical_diff(diff_data)

    # Bind to baseline_id to prevent replay across baselines
    if baseline_id:
        canonical = canonical + b"|" + baseline_id.encode()

    signature = hmac.new(secret_key, canonical, hashlib.sha256).hexdigest()

    logger.debug(
        "GAP#23: Diff signed | baseline_id=%s sig=%s...",
        baseline_id, signature[:8]
    )
    return signature


def verify_diff_signature(diff_data: Any,
                           stored_signature: str,
                           baseline_id: str = "") -> bool:
    """
    GAP #23: Verify that a diff has not been tampered with.

    Args:
        diff_data        : current diff content to verify
        stored_signature : signature stored in DB at generation time
        baseline_id      : baseline ID (must match what was used when signing)

    Returns:
        True if valid, False if tampered or invalid
    """
    if not stored_signature:
        logger.warning("GAP#23: No signature stored — diff unverified")
        return False

    try:
        expected = sign_diff(diff_data, baseline_id)
        # Constant-time comparison prevents timing attacks
        is_valid = hmac.compare_digest(stored_signature, expected)

        if not is_valid:
            logger.warning(
                "GAP#23: DIFF SIGNATURE MISMATCH — possible tampering! "
                "baseline_id=%s stored=%s... computed=%s...",
                baseline_id, stored_signature[:8], expected[:8]
            )
            # Log to security logger
            try:
                from app.core.security_logger import security_log
                security_log(
                    "diff_signature_mismatch",
                    level="CRITICAL",
                    baseline_id=baseline_id,
                    stored_sig=stored_signature[:16],
                    computed_sig=expected[:16],
                )
            except Exception:
                pass

        return is_valid

    except Exception as e:
        logger.error("GAP#23: Signature verification error: %s", e)
        return False


def create_signed_diff_response(diff_data: Any,
                                  baseline_id: str,
                                  stored_signature: str) -> dict:
    """
    Wrap a diff with its verification status for API responses.
    Always verify before returning to the approver.
    """
    is_valid = verify_diff_signature(diff_data, stored_signature, baseline_id)

    return {
        "diff":               diff_data,
        "signature":          stored_signature,
        "signature_valid":    is_valid,
        "signature_algorithm": "HMAC-SHA256",
        "warning": None if is_valid else (
            "⚠️ SECURITY ALERT: Diff signature is invalid. "
            "The diff may have been tampered with. "
            "Do NOT approve this baseline."
        ),
    }
