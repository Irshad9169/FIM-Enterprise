"""
Unit tests for app/services/cmr_session_manager.py -- the CMR (Phantom)
on-demand login mechanism modeled on the legacy get_RT_CMRs collector's
real source. Shells out to real curl (confirmed live that curl succeeds
where httpx hangs indefinitely against this specific SSO endpoint, even
with a matching User-Agent -- see the module's own docstring) -- so these
tests mock asyncio.create_subprocess_exec rather than httpx.
"""
from unittest.mock import AsyncMock, patch

import pytest

from app.services.cmr_session_manager import login_and_capture_session


def _mock_subprocess_exec(responses):
    """
    `responses`: list of (stdout_bytes, stderr_bytes, returncode) tuples,
    one per expected curl invocation, consumed in call order.
    """
    calls = iter(responses)

    async def fake_create_subprocess_exec(*args, **kwargs):
        stdout, stderr, returncode = next(calls)
        proc = AsyncMock()
        proc.communicate = AsyncMock(return_value=(stdout, stderr))
        proc.returncode = returncode
        return proc

    return fake_create_subprocess_exec


@pytest.mark.asyncio
async def test_login_fails_without_a_configured_cookie_jar_path():
    with patch("app.services.cmr_session_manager.settings") as mock_settings:
        mock_settings.cmr_cookie_jar_path = ""
        result = await login_and_capture_session("alice", "hunter2")
    assert result is False


@pytest.mark.asyncio
async def test_login_fails_when_sso_has_no_success_marker(tmp_path):
    fake_exec = _mock_subprocess_exec([
        (b"Invalid username or password", b"", 0),
    ])
    with patch("app.services.cmr_session_manager.asyncio.create_subprocess_exec", side_effect=fake_exec), \
         patch("app.services.cmr_session_manager.settings") as mock_settings:
        mock_settings.cmr_cookie_jar_path = str(tmp_path / "phantom_cookies.txt")
        mock_settings.sso_server_url = "https://auth.int.untd.com/bin/sso"
        mock_settings.cmr_sso_origin_name = "US Tickets System"
        mock_settings.cmr_sso_origin_id = "USTickets"
        mock_settings.cmr_sso_origin_url = "http://tickets.int.untd.com"

        result = await login_and_capture_session("alice", "wrong-password")

    assert result is False


@pytest.mark.asyncio
async def test_login_succeeds_with_both_curl_calls(tmp_path):
    fake_exec = _mock_subprocess_exec([
        (b"Success. Loading...", b"", 0),   # SSO login
        (b"<html>phantom front door</html>", b"", 0),  # Phantom handoff
    ])
    with patch("app.services.cmr_session_manager.asyncio.create_subprocess_exec", side_effect=fake_exec), \
         patch("app.services.cmr_session_manager.settings") as mock_settings:
        mock_settings.cmr_cookie_jar_path = str(tmp_path / "phantom_cookies.txt")
        mock_settings.sso_server_url = "https://auth.int.untd.com/bin/sso"
        mock_settings.cmr_url = "https://phantom.int.untd.com/bin/phantom"
        mock_settings.cmr_sso_origin_name = "US Tickets System"
        mock_settings.cmr_sso_origin_id = "USTickets"
        mock_settings.cmr_sso_origin_url = "http://tickets.int.untd.com"

        result = await login_and_capture_session("alice", "correct-password")

    assert result is True


@pytest.mark.asyncio
async def test_login_fails_when_curl_itself_errors(tmp_path):
    fake_exec = _mock_subprocess_exec([
        (b"", b"curl: (60) SSL certificate problem", 60),
    ])
    with patch("app.services.cmr_session_manager.asyncio.create_subprocess_exec", side_effect=fake_exec), \
         patch("app.services.cmr_session_manager.settings") as mock_settings:
        mock_settings.cmr_cookie_jar_path = str(tmp_path / "phantom_cookies.txt")
        mock_settings.sso_server_url = "https://auth.int.untd.com/bin/sso"
        mock_settings.cmr_sso_origin_name = "US Tickets System"
        mock_settings.cmr_sso_origin_id = "USTickets"
        mock_settings.cmr_sso_origin_url = "http://tickets.int.untd.com"

        result = await login_and_capture_session("alice", "hunter2")

    assert result is False


@pytest.mark.asyncio
async def test_login_fails_when_phantom_handoff_fails_after_sso_success(tmp_path):
    fake_exec = _mock_subprocess_exec([
        (b"Success. Loading...", b"", 0),        # SSO login succeeds
        (b"", b"curl: (28) timeout", 28),          # Phantom handoff fails
    ])
    with patch("app.services.cmr_session_manager.asyncio.create_subprocess_exec", side_effect=fake_exec), \
         patch("app.services.cmr_session_manager.settings") as mock_settings:
        mock_settings.cmr_cookie_jar_path = str(tmp_path / "phantom_cookies.txt")
        mock_settings.sso_server_url = "https://auth.int.untd.com/bin/sso"
        mock_settings.cmr_url = "https://phantom.int.untd.com/bin/phantom"
        mock_settings.cmr_sso_origin_name = "US Tickets System"
        mock_settings.cmr_sso_origin_id = "USTickets"
        mock_settings.cmr_sso_origin_url = "http://tickets.int.untd.com"

        result = await login_and_capture_session("alice", "correct-password")

    assert result is False


@pytest.mark.asyncio
async def test_login_never_logs_the_password(caplog):
    import logging
    caplog.set_level(logging.DEBUG, logger="cmr_session_manager")

    async def raise_exec(*args, **kwargs):
        raise RuntimeError("curl not found")

    with patch("app.services.cmr_session_manager.asyncio.create_subprocess_exec", side_effect=raise_exec), \
         patch("app.services.cmr_session_manager.settings") as mock_settings:
        mock_settings.cmr_cookie_jar_path = "/tmp/whatever.txt"
        mock_settings.sso_server_url = "https://auth.int.untd.com/bin/sso"
        mock_settings.cmr_sso_origin_name = "US Tickets System"
        mock_settings.cmr_sso_origin_id = "USTickets"
        mock_settings.cmr_sso_origin_url = "http://tickets.int.untd.com"

        await login_and_capture_session("alice", "super-secret-password")

    assert "super-secret-password" not in caplog.text


@pytest.mark.asyncio
async def test_login_url_encodes_special_characters_in_credentials(tmp_path):
    # A password containing URL-reserved characters (&, =, spaces) must be
    # percent-encoded, or it would corrupt the query string curl receives.
    captured_calls = []

    async def fake_exec(*args, **kwargs):
        captured_calls.append(args)
        proc = AsyncMock()
        proc.communicate = AsyncMock(return_value=(b"Success. Loading...", b""))
        proc.returncode = 0
        return proc

    with patch("app.services.cmr_session_manager.asyncio.create_subprocess_exec", side_effect=fake_exec), \
         patch("app.services.cmr_session_manager.settings") as mock_settings:
        mock_settings.cmr_cookie_jar_path = str(tmp_path / "phantom_cookies.txt")
        mock_settings.sso_server_url = "https://auth.int.untd.com/bin/sso"
        mock_settings.cmr_url = "https://phantom.int.untd.com/bin/phantom"
        mock_settings.cmr_sso_origin_name = "US Tickets System"
        mock_settings.cmr_sso_origin_id = "USTickets"
        mock_settings.cmr_sso_origin_url = "http://tickets.int.untd.com"

        await login_and_capture_session("alice", "p@ss&word=1 two")

    login_call_args = next(c for c in captured_calls if any(a.startswith("https://auth.int.untd.com") for a in c))
    url_arg = next(a for a in login_call_args if a.startswith("https://auth.int.untd.com"))
    assert "password=p%40ss%26word%3D1%20two" in url_arg
    assert "&word=1" not in url_arg  # would indicate an unescaped '&' broke the query string
