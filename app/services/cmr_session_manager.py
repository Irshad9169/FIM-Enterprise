"""
CMR (Phantom) session auto-refresh.

Phantom has no dedicated API -- only its own web UI behind company SSO,
confirmed by direct testing (a bare sso_token request returns an actual
SSO login page, not data). The legacy `get_RT_CMRs` collector's real
source (its own `authenticate.cgi` + `get_RT_CMRs`) shows how it actually
gets around this: it isn't a service account at all, it's a direct
username+password call to the SSO server's own `type=login` mode
(different from the interactive browser-redirect SSO flow used elsewhere
in this app), which returns a cookie that's then presented to Phantom's
own front door once to receive a Phantom-specific session cookie. That
legacy system only refreshes this when a human happens to log into its
web form; this module does the same two-hop login on a schedule instead,
and writes the result to settings.cmr_cookie_jar_path in the same
Netscape cookie-file format app.services.ticket_linker._load_cmr_cookies
already reads -- so nothing downstream of that function needs to change.

UNVERIFIED end-to-end: the type=login SSO mode and the Phantom
session-cookie handoff are proven by the legacy source, but only using
its own already-registered SSO origin ("USTickets"). Whether the SSO
server accepts a different origin_id (FIM's own) for this exact login
mode has not been tested against the real servers.
"""
import asyncio
import http.cookiejar
import logging
import os

import httpx

from app.core.config import settings

logger = logging.getLogger("cmr_session_manager")

HTTPX_OPTS = dict(verify=False, timeout=15.0, follow_redirects=True)

# The legacy collector detects a successful SSO login by string-matching
# this exact text in the response body -- there's no structured
# success/error response from this endpoint.
_SSO_LOGIN_SUCCESS_MARKER = "Success. Loading..."


def _save_cookies_to_jar(cookies: httpx.Cookies, path: str) -> None:
    """
    Persist an httpx client's accumulated cookies to a Netscape-format
    cookie file at `path`, overwriting whatever was there. ignore_discard/
    ignore_expires=True on save (mirroring _load_cmr_cookies's own load-time
    handling) so a session cookie with no fixed expiry still gets written
    instead of silently dropped.
    """
    directory = os.path.dirname(path)
    if directory:
        os.makedirs(directory, exist_ok=True)
    jar = http.cookiejar.MozillaCookieJar(path)
    for cookie in cookies.jar:
        jar.set_cookie(cookie)
    jar.save(ignore_discard=True, ignore_expires=True)


class CMRSessionManager:
    """Background task that keeps settings.cmr_cookie_jar_path populated
    with a live Phantom session, refreshed every cmr_session_refresh_minutes."""

    def __init__(self):
        self.enabled = bool(
            settings.cmr_sso_username
            and settings.cmr_sso_password
            and settings.cmr_cookie_jar_path
        )
        self.refresh_minutes = settings.cmr_session_refresh_minutes
        self._task: asyncio.Task = None
        self._running = False

    async def refresh_once(self) -> bool:
        """
        Log in and capture a fresh Phantom session, mirroring the legacy
        collector's own two curl calls:
          1. auth.int.untd.com/bin/sso?...&type=login&username=&password=
          2. present that cookie to phantom's own front door once
        Returns True on success, False on any failure -- never raises,
        since a failed refresh should just leave the previous (possibly
        still-valid) cookie file in place rather than crash anything.
        """
        try:
            async with httpx.AsyncClient(**HTTPX_OPTS) as client:
                login_resp = await client.get(settings.sso_server_url, params={
                    "async":       "true",
                    "action":      "parms",
                    "type":        "login",
                    "username":    settings.cmr_sso_username,
                    "password":    settings.cmr_sso_password,
                    "origin_name": settings.cmr_sso_origin_name,
                    "origin_id":   settings.cmr_sso_origin_id,
                    "origin_url":  settings.cmr_sso_origin_url,
                })
                if _SSO_LOGIN_SUCCESS_MARKER not in login_resp.text:
                    logger.error(
                        "CMR session refresh: SSO login did not return the "
                        "expected success marker -- check cmr_sso_username/"
                        "cmr_sso_password/cmr_sso_origin_* and whether this "
                        "SSO server still supports type=login for this origin"
                    )
                    return False

                # Present the SSO cookie to Phantom's own front door once --
                # this is the step that (per the legacy source's observed
                # behavior) gets Phantom to hand back its own session cookie.
                await client.get(settings.cmr_url)

                _save_cookies_to_jar(client.cookies, settings.cmr_cookie_jar_path)
                logger.info(
                    f"CMR session refreshed, saved to {settings.cmr_cookie_jar_path}"
                )
                return True
        except Exception as e:
            logger.error(f"CMR session refresh failed: {e}")
            return False

    async def _loop(self):
        while self._running:
            await self.refresh_once()
            try:
                await asyncio.sleep(self.refresh_minutes * 60)
            except asyncio.CancelledError:
                break

    async def start(self):
        if not self.enabled:
            logger.info(
                "CMR session auto-refresh is DISABLED "
                "(cmr_sso_username/cmr_sso_password/cmr_cookie_jar_path not all set)"
            )
            return
        self._running = True
        self._task = asyncio.create_task(self._loop())
        logger.info(
            f"CMR session auto-refresh started, every {self.refresh_minutes} minutes"
        )

    def stop(self):
        self._running = False
        if self._task:
            self._task.cancel()
