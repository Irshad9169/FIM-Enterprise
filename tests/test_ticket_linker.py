"""
Unit tests for app/services/ticket_linker.py's CMR (Phantom) auth path.

Covers a real bug: search_cmr_by_hostname() used to send the FIM user's
own JWT to Phantom as sso_token, which Phantom has no concept of -- CMR
access only ever works via the externally-maintained cookie jar (see
_load_cmr_cookies / fetch_recent_implemented_cmrs). No real network or
database access -- fetch_recent_implemented_cmrs is mocked so these stay
pure unit tests of the filtering/detection logic itself.
"""
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from app.services.ticket_linker import TicketLinkerService, _host_base_name, _host_matches


# ── _host_base_name / _host_matches ─────────────────────────────────────────

def test_host_base_name_strips_trailing_instance_number():
    assert _host_base_name("web-prod-01") == "web-prod"
    assert _host_base_name("web01") == "web"
    assert _host_base_name("test06") == "test"


def test_host_matches_is_word_boundary_safe():
    # Regression: a plain substring check would wrongly match "web01"
    # inside "web010", or a host's number inside an unrelated longer one.
    assert _host_matches("web01", "web010 was changed") is False
    assert _host_matches("web01", "web01 was changed") is True


def test_host_matches_falls_back_to_base_name():
    # "web-prod-05" isn't mentioned anywhere, but its group name is.
    assert _host_matches("web-prod-05", "the web-prod cluster was patched") is True


def test_host_matches_does_not_use_short_base_names():
    # "db01" -> base "db" is only 2 chars -- too short/generic to use as a
    # fuzzy match without flooding every host named db* with false hits.
    assert _host_matches("db01", "DB is down for unrelated reasons") is False


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


async def test_search_cmr_by_hostname_matches_description_and_rollout_plan():
    # Boris's own correlation greps a CMR's whole record, not just
    # Server(s) Affected -- description/rollout_plan need to count too.
    cmrs = [{
        "ticket_id": "222333", "status": "Implemented",
        "servers_affected": "", "resolved_hosts": [],
        "description": "Patch rollout for web-prod-07",
        "rollout_plan": "Restart nginx on web-prod-07 after patching",
        "url": "https://phantom.example/222333",
    }]
    with patch.object(
        TicketLinkerService, "fetch_recent_implemented_cmrs", return_value=cmrs
    ):
        results = await TicketLinkerService.search_cmr_by_hostname("web-prod-07")

    assert [r["ticket_id"] for r in results] == ["222333"]


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


# ── _match_cmrs_to_hostname / correlate_all_agents CMR fetch count ──────────

def test_match_cmrs_to_hostname_is_pure_no_fetch():
    cmrs = [{
        "ticket_id": "111111", "status": "Implemented",
        "servers_affected": "web-prod-01", "resolved_hosts": [],
        "description": "", "rollout_plan": "", "url": "https://phantom.example/111111",
    }]
    results = TicketLinkerService._match_cmrs_to_hostname(cmrs, "web-prod-01")
    assert [r["ticket_id"] for r in results] == ["111111"]


async def test_correlate_all_agents_fetches_cmrs_once_not_per_host():
    # Regression guard for the real bug this whole fix addresses: with N
    # hosts, this used to call fetch_recent_implemented_cmrs N times (each
    # one independently re-running the full per-CMR detail fetch against
    # Phantom), producing enough rapid repeated traffic to look like abuse.
    db = AsyncMock()
    db.execute = AsyncMock(return_value=SimpleNamespace(fetchall=lambda: [], fetchone=lambda: None))

    fetch_calls = []

    async def fake_fetch(days_back=5):
        fetch_calls.append(days_back)
        return []

    with patch.object(TicketLinkerService, "fetch_recent_implemented_cmrs", side_effect=fake_fetch), \
         patch.object(TicketLinkerService, "search_rt_by_hostname", return_value=[]), \
         patch.object(TicketLinkerService, "search_jira_by_hostname", return_value=[]), \
         patch.object(TicketLinkerService, "_upsert_report_ticket", return_value=None), \
         patch.object(TicketLinkerService, "_notify_unmatched_changes", return_value=None):
        await TicketLinkerService.correlate_all_agents(
            "report-1", ["host1", "host2", "host3", "host4", "host5"], "token", db
        )

    assert fetch_calls == [30]  # exactly one call, preserving the 30-day window


# ── _notify_unmatched_changes ────────────────────────────────────────────────

async def test_notify_unmatched_changes_emails_admin_analyst_recipients():
    db = AsyncMock()
    date_result   = SimpleNamespace(first=lambda: SimpleNamespace(report_date="2026-09-17"))
    recip_result  = SimpleNamespace(
        fetchall=lambda: [SimpleNamespace(email="admin@example.com"), SimpleNamespace(email="analyst@example.com")]
    )
    db.execute = AsyncMock(side_effect=[date_result, recip_result])

    with patch("app.services.email_service.EmailService.notify_unmatched_changes") as mock_notify:
        await TicketLinkerService._notify_unmatched_changes("report-1", ["host1", "host2"], db)

    mock_notify.assert_called_once_with(
        "2026-09-17", ["host1", "host2"], ["admin@example.com", "analyst@example.com"]
    )


async def test_notify_unmatched_changes_skips_send_with_no_recipients():
    db = AsyncMock()
    date_result  = SimpleNamespace(first=lambda: SimpleNamespace(report_date="2026-09-17"))
    recip_result = SimpleNamespace(fetchall=lambda: [])
    db.execute = AsyncMock(side_effect=[date_result, recip_result])

    with patch("app.services.email_service.EmailService.notify_unmatched_changes") as mock_notify:
        await TicketLinkerService._notify_unmatched_changes("report-1", ["host1"], db)

    mock_notify.assert_not_called()


async def test_notify_unmatched_changes_never_raises_on_db_error():
    db = AsyncMock()
    db.execute = AsyncMock(side_effect=RuntimeError("db is down"))

    # Must not propagate -- this runs after correlate_all_agents has already
    # committed; a notification failure must never surface as a 500 there.
    await TicketLinkerService._notify_unmatched_changes("report-1", ["host1"], db)


# ── SSO login page detection ────────────────────────────────────────────────

def test_looks_like_sso_login_page_detects_real_title():
    html = "<html><head><title>United Online Single Sign-On</title></head></html>"
    assert TicketLinkerService._looks_like_sso_login_page(html) is True


def test_looks_like_sso_login_page_false_for_real_results():
    html = "<html><body>CMR #123456 Implemented</body></html>"
    assert TicketLinkerService._looks_like_sso_login_page(html) is False


# ── has_valid_cmr_session ────────────────────────────────────────────────────

def test_has_valid_cmr_session_true_when_cookies_present():
    with patch.object(TicketLinkerService, "_load_cmr_cookies", return_value={"phantom_sessionid": "x"}):
        assert TicketLinkerService.has_valid_cmr_session() is True


def test_has_valid_cmr_session_false_when_no_cookies():
    with patch.object(TicketLinkerService, "_load_cmr_cookies", return_value=None):
        assert TicketLinkerService.has_valid_cmr_session() is False


# ── _extract_field ──────────────────────────────────────────────────────────
# Regression coverage for a real bug: a real Phantom viewrequest page packs
# several "Label: value" pairs onto the same rendered block with no line
# break between them, so the old per-line `line.startswith("Owner:")` style
# checks never matched -- Owner/Status/Start Time rendered empty in the CMR
# widget even though the label text itself had been guessed correctly.

_REAL_CMR_TEXT = (
    "Request Status: Status: Implemented Owner: 'Alan Finney' "
    "ImplementorOwner: 'John Smith P. G. V. V.' "
    "Basic Actions: Add Notes Copy Refresh View Printable Expand All "
    "Basic Request Data Request ID: 123456 Status: Implemented "
    "Submission Date: 2026-09-15 15:45:15 Reviewer: 'Bill Bowen' "
    "Category: Data Product Line: Lingo Service(s) Affected: ICE "
    "Component(s) Affected: Database "
    "Server(s) Affected: sql-cloud.corp.xyz.com "
    "Description: Remove MyAccount login for 41238... More... "
    "Type: Normal "
    "Implementation Data Implementor: 'DBAlerts' "
    "Start Time: 2026-09-16 09:00 End Time: 2026-09-17 09:00 "
    "Downtime: None Rollout Plan: Execute script... More... "
    "Request History Date and Time Event "
    "2026-09-15 15:45:15 Created and submitted by 'Alan Finney'"
)


def test_extract_field_finds_owner_not_implementor_owner():
    # "ImplementorOwner:" contains "Owner:" as a substring -- must not
    # false-match there instead of the real, standalone "Owner:" label.
    assert TicketLinkerService._extract_field(
        _REAL_CMR_TEXT, "Owner", ["ImplementorOwner:", "Basic Request Data"]
    ) == "Alan Finney"


def test_extract_field_finds_status_not_request_status_header():
    # "Request Status:" (a section header) also ends in the substring
    # "Status:" -- must not false-match there instead of the real
    # "Status: Implemented" pair inside "Basic Request Data".
    basic_idx = _REAL_CMR_TEXT.find("Basic Request Data")
    section = _REAL_CMR_TEXT[basic_idx:]
    assert TicketLinkerService._extract_field(section, "Status", ["Submission Date:"]) == "Implemented"


def test_extract_field_finds_start_time_with_real_label():
    # The real label is "Start Time:", not the earlier guessed
    # "Implementation Start" (which never appears on a real page at all).
    assert TicketLinkerService._extract_field(
        _REAL_CMR_TEXT, "Start Time", ["End Time:"]
    ) == "2026-09-16 09:00"


def test_extract_field_stops_servers_affected_before_next_label():
    # Regression: the old code took the rest of the *line*, which on a
    # real page swallows the following "Description: ..." text too since
    # both are packed onto the same block.
    assert TicketLinkerService._extract_field(
        _REAL_CMR_TEXT, "Server(s) Affected", ["Description:"]
    ) == "sql-cloud.corp.xyz.com"


def test_extract_field_returns_empty_when_label_absent():
    assert TicketLinkerService._extract_field(_REAL_CMR_TEXT, "Nonexistent Field", ["End Time:"]) == ""
