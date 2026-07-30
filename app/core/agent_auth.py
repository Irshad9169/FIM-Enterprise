"""
Real per-agent API key verification.

Fixes a pre-existing gap: app/api/scans.py's signature check used to compute
the "expected" HMAC from the X-API-Key header of the SAME incoming request —
a self-consistency check any caller can satisfy by inventing their own key.
app/api/agents.py's /register and /heartbeat checked no header at all.

Design: trust-on-first-contact, mirroring Agent.binary_hash (already built
and validated this session). The first request for a given agent record
establishes the accepted key (as a hash, never plaintext); every request
after that must match it. Every agent already sends X-API-Key on every
request via FIMClient's persistent session headers, so no agent-side
changes are needed to start enforcing this.
"""
import hashlib
import hmac

from app.models.models import Agent


def hash_agent_key(key: str) -> str:
    return hashlib.sha256(key.encode("utf-8")).hexdigest()


def check_agent_key(agent: Agent, provided_key: str) -> bool:
    """
    True if authorized. If agent.api_key_hash is unset (brand-new agent, or
    one that registered before this feature existed), establishes it from
    provided_key and returns True — same bootstrap concession already used
    for Agent.binary_hash, so already-deployed agents don't need manual
    re-provisioning.
    """
    if not agent.api_key_hash:
        if not provided_key:
            return False
        agent.api_key_hash = hash_agent_key(provided_key)
        return True
    return bool(provided_key) and hmac.compare_digest(hash_agent_key(provided_key), agent.api_key_hash)
