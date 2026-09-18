"""
CMR (Phantom) on-demand session login.

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
web form -- this module does the exact same thing, on demand, triggered
from the Correlate All button when there's no valid session yet, using
whatever username/password the analyst enters at that moment.

FIM cannot substitute the already-logged-in FIM user's own credentials
here even if it wanted to: confirmed by reading the code, neither of
FIM's own login paths ever puts a real corporate SSO password in FIM's
hands -- the password login (app/api/auth_enhanced.py) checks a
password against FIM's own locally-stored hash (a completely different
credential from the corporate SSO password), and the SSO login
(app/api/auth_sso.py) is a browser-redirect flow that never gives FIM
the raw password at all. So this has to be its own, separate prompt.

The username/password passed to login_and_capture_session() are used
only for the one login request below -- never logged, never written to
disk, never stored on this object or anywhere else. Only the resulting
session cookie is persisted (to settings.cmr_cookie_jar_path, in the
same Netscape format app.services.ticket_linker._load_cmr_cookies
already reads, so nothing downstream needs to change).

UNVERIFIED end-to-end: the type=login SSO mode and the Phantom
session-cookie handoff are proven by the legacy source, but only using
its own already-registered SSO origin ("USTickets"). Whether the SSO
server accepts a different origin_id (FIM's own) for this exact login
mode has not been tested against the real servers.
"""
import http.cookiejar
import logging
import os

import httpx

from app.core.config import settings

logger = logging.getLogger("cmr_session_manager")

# The legacy collector's curl calls have no explicit timeout at all (curl's
# own default is very long) -- a live ReadTimeout at 15s here showed that
# was too aggressive for this specific SSO login mode, whatever the SSO
# server is doing server-side to process it.
HTTPX_OPTS = dict(verify=False, timeout=60.0, follow_redirects=True)

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


async def login_and_capture_session(username: str, password: str) -> bool:
    """
    One-shot login, mirroring get_RT_CMRs's own two curl calls:
      1. auth.int.untd.com/bin/sso?...&type=login&username=&password=
      2. present that cookie to Phantom's own front door once
    Returns True on success (session saved to settings.cmr_cookie_jar_path),
    False on any failure -- never raises, so a bad credential just means
    "CMR fetch stays skipped this time", not a crash.
    """
    if not settings.cmr_cookie_jar_path:
        logger.error("login_and_capture_session: CMR_COOKIE_JAR_PATH not configured")
        return False
    try:
        async with httpx.AsyncClient(**HTTPX_OPTS) as client:
            login_resp = await client.get(settings.sso_server_url, params={
                "async":       "true",
                "action":      "parms",
                "type":        "login",
                "username":    username,
                "password":    password,
                "origin_name": settings.cmr_sso_origin_name,
                "origin_id":   settings.cmr_sso_origin_id,
                "origin_url":  settings.cmr_sso_origin_url,
            })
            if _SSO_LOGIN_SUCCESS_MARKER not in login_resp.text:
                # Safe to log: this is the SSO server's own response text,
                # not the submitted credential. Truncated since some SSO
                # error pages can be large HTML documents.
                logger.warning(
                    "CMR session login: SSO did not return the expected "
                    "success marker -- likely a wrong username/password, or "
                    "this SSO server doesn't accept type=login for this "
                    f"origin. HTTP {login_resp.status_code}, body starts: "
                    f"{login_resp.text[:300]!r}"
                )
                return False

            # Present the SSO cookie to Phantom's own front door once --
            # this is the step that (per the legacy source's observed
            # behavior) gets Phantom to hand back its own session cookie.
            await client.get(settings.cmr_url)

            _save_cookies_to_jar(client.cookies, settings.cmr_cookie_jar_path)
            logger.info(
                f"CMR session established, saved to {settings.cmr_cookie_jar_path}"
            )
            return True
    except Exception as e:
        # str(e) alone can be an empty string for some exception types
        # (several httpx/network errors included) -- log the exception
        # type and a full traceback too, or a failure here is
        # undiagnosable from the logs alone.
        logger.error(f"CMR session login failed: {type(e).__name__}: {e}", exc_info=True)
        return False
