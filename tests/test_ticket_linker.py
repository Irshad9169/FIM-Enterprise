"""
Unit tests for app/services/ticket_linker.py's CMR (Phantom) auth path.

Covers a real bug: search_cmr_by_hostname() used to send the FIM user's
own JWT to Phantom as sso_token, which Phantom has no concept of -- CMR
access only ever works via the externally-maintained cookie jar (see
_load_cmr_cookies / fetch_recent_implemented_cmrs). No real network or
database access -- fetch_recent_implemented_cmrs is mocked so these stay
pure unit tests of the filtering/detection logic itself.
"""
from unittest.mock import patch

from app.services.ticket_linker import TicketLinkerService


# ── search_cmr_by_hostname ───────────────────────────────────────────────────

async def test_search_cmr_by_hostname_matches_servers_affected():
    cmrs = [
        {
            "ticket_id": "123456", "status": "Implemented",
            "servers_affected": "web-prod-01 web-prod-02",
            "resolved_hosts": [], "url": "https://phantom.example/123456",
        },
        {
            "ticket_id": "654321", "status": "Implemented",
            "servers_affected": "db-prod-01",
            "resolved_hosts": [], "url": "https://phantom.example/654321",
        },
    ]
    with patch.object(
        TicketLinkerService, "fetch_recent_implemented_cmrs", return_value=cmrs
    ):
        results = await TicketLinkerService.search_cmr_by_hostname("web-prod-01.int.untd.com")

    assert [r["ticket_id"] for r in results] == ["123456"]


async def test_search_cmr_by_hostname_matches_resolved_hosts():
    cmrs = [{
        "ticket_id": "111222", "status": "Approved",
        "servers_affected": "web-prod",  # logical name only
        "resolved_hosts": ["web-prod-03", "web-prod-04"],
        "url": "https://phantom.example/111222",
    }]
    with patch.object(
        TicketLinkerService, "fetch_recent_implemented_cmrs", return_value=cmrs
    ):
        results = await TicketLinkerService.search_cmr_by_hostname("web-prod-04")

    assert [r["ticket_id"] for r in results] == ["111222"]


async def test_search_cmr_by_hostname_no_match_returns_empty():
    cmrs = [{
        "ticket_id": "999999", "status": "Implemented",
        "servers_affected": "unrelated-host", "resolved_hosts": [],
        "url": "https://phantom.example/999999",
    }]
    with patch.object(
        TicketLinkerService, "fetch_recent_implemented_cmrs", return_value=cmrs
    ):
        results = await TicketLinkerService.search_cmr_by_hostname("web-prod-01")

    assert results == []


async def test_search_cmr_by_hostname_no_cookie_returns_empty():
    # fetch_recent_implemented_cmrs itself returns [] when no CMR cookie
    # jar is configured -- search_cmr_by_hostname must fail the same safe
    # way, not raise.
    with patch.object(
        TicketLinkerService, "fetch_recent_implemented_cmrs", return_value=[]
    ):
        results = await TicketLinkerService.search_cmr_by_hostname("anything")

    assert results == []


async def test_search_cmr_by_hostname_does_not_take_a_token():
    # Regression guard for the actual bug: this call used to require (and
    # misuse) a FIM JWT as `token`. New signature is (hostname, days_back).
    import inspect
    sig = inspect.signature(TicketLinkerService.search_cmr_by_hostname)
    assert "token" not in sig.parameters


# ── SSO login page detection ────────────────────────────────────────────────

def test_looks_like_sso_login_page_detects_real_title():
    html = "<html><head><title>United Online Single Sign-On</title></head></html>"
    assert TicketLinkerService._looks_like_sso_login_page(html) is True


def test_looks_like_sso_login_page_false_for_real_results():
    html = "<html><body>CMR #123456 Implemented</body></html>"
    assert TicketLinkerService._looks_like_sso_login_page(html) is False
