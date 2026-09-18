"""
Unit tests for app/services/cmr_session_manager.py -- the CMR (Phantom)
on-demand login mechanism modeled on the legacy get_RT_CMRs collector's
real source. No live SSO/Phantom calls (can't be tested from here) --
httpx is mocked; the one thing genuinely verified end-to-end is that
_save_cookies_to_jar produces a file
app.services.ticket_linker.TicketLinkerService._load_cmr_cookies can
actually read back, since that's the whole point of writing to the same
cookie-jar path the existing (already-proven) CMR fetch code reads from.
"""
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest

from app.services.cmr_session_manager import _save_cookies_to_jar, login_and_capture_session
from app.services.ticket_linker import TicketLinkerService


def test_save_cookies_to_jar_is_readable_by_load_cmr_cookies(tmp_path):
    jar_path = str(tmp_path / "phantom_cookies.txt")

    cookies = httpx.Cookies()
    cookies.set("sso_auth", "sometoken", domain="auth.int.untd.com")
    cookies.set("phantom_sessionid", "abc123", domain="phantom.int.untd.com")

    _save_cookies_to_jar(cookies, jar_path)

    with patch("app.services.ticket_linker.settings") as mock_settings:
        mock_settings.cmr_cookie_jar_path = jar_path
        loaded = TicketLinkerService._load_cmr_cookies()

    assert loaded == {"sso_auth": "sometoken", "phantom_sessionid": "abc123"}


def _mock_client(get_side_effect):
    client = AsyncMock()
    client.get = AsyncMock(side_effect=get_side_effect)
    client.cookies = httpx.Cookies()
    ctx = MagicMock()
    ctx.__aenter__ = AsyncMock(return_value=client)
    ctx.__aexit__ = AsyncMock(return_value=False)
    return ctx


@pytest.mark.asyncio
async def test_login_fails_without_a_configured_cookie_jar_path():
    with patch("app.services.cmr_session_manager.settings") as mock_settings:
        mock_settings.cmr_cookie_jar_path = ""
        result = await login_and_capture_session("alice", "hunter2")
    assert result is False


@pytest.mark.asyncio
async def test_login_fails_when_sso_has_no_success_marker(tmp_path):
    login_resp = MagicMock(text="Invalid username or password")
    ctx = _mock_client([login_resp])

    with patch("app.services.cmr_session_manager.httpx.AsyncClient", return_value=ctx), \
         patch("app.services.cmr_session_manager.settings") as mock_settings:
        mock_settings.cmr_cookie_jar_path = str(tmp_path / "phantom_cookies.txt")
        mock_settings.sso_server_url = "https://auth.int.untd.com/bin/sso"
        mock_settings.cmr_sso_origin_name = "FIM Enterprise"
        mock_settings.cmr_sso_origin_id = "FIM_ENTERPRISE"
        mock_settings.cmr_sso_origin_url = ""

        result = await login_and_capture_session("alice", "wrong-password")

    assert result is False


@pytest.mark.asyncio
async def test_login_succeeds_and_saves_cookies(tmp_path):
    jar_path = str(tmp_path / "phantom_cookies.txt")
    login_resp = MagicMock(text="Success. Loading...")
    phantom_resp = MagicMock(text="<html>ok</html>")
    ctx = _mock_client([login_resp, phantom_resp])

    with patch("app.services.cmr_session_manager.httpx.AsyncClient", return_value=ctx), \
         patch("app.services.cmr_session_manager.settings") as mock_settings, \
         patch("app.services.cmr_session_manager._save_cookies_to_jar") as mock_save:
        mock_settings.sso_server_url = "https://auth.int.untd.com/bin/sso"
        mock_settings.cmr_url = "https://phantom.int.untd.com/bin/phantom"
        mock_settings.cmr_sso_origin_name = "FIM Enterprise"
        mock_settings.cmr_sso_origin_id = "FIM_ENTERPRISE"
        mock_settings.cmr_sso_origin_url = ""
        mock_settings.cmr_cookie_jar_path = jar_path

        result = await login_and_capture_session("alice", "correct-password")

    assert result is True
    mock_save.assert_called_once()
    assert mock_save.call_args[0][1] == jar_path


@pytest.mark.asyncio
async def test_login_swallows_exceptions():
    with patch("app.services.cmr_session_manager.httpx.AsyncClient", side_effect=RuntimeError("network down")), \
         patch("app.services.cmr_session_manager.settings") as mock_settings:
        mock_settings.cmr_cookie_jar_path = "/tmp/whatever.txt"
        result = await login_and_capture_session("alice", "hunter2")
    assert result is False


@pytest.mark.asyncio
async def test_login_never_logs_the_password(caplog):
    # Regression guard: nothing in this module should ever put the raw
    # password into a log line.
    import logging
    caplog.set_level(logging.DEBUG, logger="cmr_session_manager")
    with patch("app.services.cmr_session_manager.httpx.AsyncClient", side_effect=RuntimeError("boom")), \
         patch("app.services.cmr_session_manager.settings") as mock_settings:
        mock_settings.cmr_cookie_jar_path = "/tmp/whatever.txt"
        await login_and_capture_session("alice", "super-secret-password")
    assert "super-secret-password" not in caplog.text
