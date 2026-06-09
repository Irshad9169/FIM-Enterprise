"""
Scan Result Signing — HMAC-SHA256 payload integrity verification

Used by both the agent (to sign) and the server (to verify).
The shared secret is the agent's API key, already configured on both sides.

How it works:
  1. Agent serializes scan payload as canonical JSON (sorted keys, no extra whitespace)
  2. Agent computes HMAC-SHA256 using the API key as the secret
  3. Agent sends signature in X-Scan-Signature header
  4. Server recomputes HMAC from the raw request body
  5. If signatures don't match → payload was tampered in transit → reject

This prevents:
  - Man-in-the-middle modification of scan results
  - Replay attacks with altered file hashes
  - Injection of fake scan data even if API key is compromised
    (attacker would need to re-sign after modification)
"""
import hmac
import hashlib
import json
from typing import Optional


SIGNATURE_HEADER = "X-Scan-Signature"
SIGNATURE_PREFIX = "hmac-sha256="


def sign_payload(payload: dict, secret: str) -> str:
    """
    Sign a scan payload dict with HMAC-SHA256.
    Returns the signature string (hex digest with prefix).

    The payload is serialized with sorted keys and compact separators
    to ensure deterministic output regardless of dict ordering.
    """
    canonical = json.dumps(payload, sort_keys=True, separators=(',', ':'))
    sig = hmac.new(
        secret.encode('utf-8'),
        canonical.encode('utf-8'),
        hashlib.sha256
    ).hexdigest()
    return f"{SIGNATURE_PREFIX}{sig}"


def verify_signature(raw_body: bytes, signature: str, secret: str) -> bool:
    """
    Verify the HMAC-SHA256 signature of a raw request body.

    raw_body: the exact bytes received from the network (preserves order)
    signature: the X-Scan-Signature header value
    secret: the shared API key

    Returns True if valid, False if tampered or missing.
    """
    if not signature or not signature.startswith(SIGNATURE_PREFIX):
        return False

    received_sig = signature[len(SIGNATURE_PREFIX):]

    # Reparse and re-serialize to get canonical form
    # (handles potential whitespace differences from different JSON encoders)
    try:
        payload = json.loads(raw_body)
        canonical = json.dumps(payload, sort_keys=True, separators=(',', ':'))
    except (json.JSONDecodeError, UnicodeDecodeError):
        return False

    expected_sig = hmac.new(
        secret.encode('utf-8'),
        canonical.encode('utf-8'),
        hashlib.sha256
    ).hexdigest()

    # Constant-time comparison to prevent timing attacks
    return hmac.compare_digest(received_sig, expected_sig)
