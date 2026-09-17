"""
Unit tests for app/services/email_service.py's notify_unmatched_changes --
the "no RT/CMR found" notification mirroring boris-scan-report's own
behavior (see ticket_linker.py's correlate_all_agents). No real sendmail
call -- send_email is mocked.
"""
from unittest.mock import patch

from app.services.email_service import EmailService


def test_notify_unmatched_changes_includes_all_hosts_and_count():
    with patch.object(EmailService, "send_email", return_value=True) as mock_send:
        EmailService.notify_unmatched_changes(
            "2026-09-17", ["web01.int.untd.com", "db02.int.untd.com"], ["admin@example.com"]
        )

    mock_send.assert_called_once()
    to, subject, body = mock_send.call_args[0][:3]
    assert to == ["admin@example.com"]
    assert "2 host(s)" in subject
    assert "web01.int.untd.com" in body
    assert "db02.int.untd.com" in body


def test_notify_unmatched_changes_returns_send_email_result():
    with patch.object(EmailService, "send_email", return_value=False):
        result = EmailService.notify_unmatched_changes("2026-09-17", ["host1"], ["a@example.com"])
    assert result is False
