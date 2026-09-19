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
disk, never stored anywhere. Only the resulting session cookie is
persisted (to settings.cmr_cookie_jar_path, written directly by curl in
the same Netscape format app.services.ticket_linker._load_cmr_cookies
already reads, so nothing downstream needs to change).

CONFIRMED live (2026-09-18/19): the type=login SSO call works and
responds in ~1s using the legacy origin ("USTickets", see
settings.cmr_sso_origin_*) -- but silently hangs indefinitely (no
response, no error) when given a different origin_id, including FIM's
own. Don't change cmr_sso_origin_name/cmr_sso_origin_id/cmr_sso_origin_url
away from the legacy values without re-testing directly against the real
SSO server first.

Also confirmed live: an *identical* request (same URL, params, origin)
succeeds in ~1s via real curl but hangs indefinitely via httpx -- even
after matching curl's own User-Agent string, ruling out a header-based
explanation. Most consistent with a security layer in front of the SSO
server fingerprinting the TLS client itself (JA3-style), which an
HTTP-level User-Agent override can't spoof. The legacy Boris team hit
the same category of connectivity issue with this exact endpoint
(a stale CA bundle on their end) and always resolved it by working with
real curl directly, never by switching to a different HTTP client --
consistent with curl being the one client this SSO endpoint reliably
answers for. So this module shells out to real curl for both hops
instead of using httpx, exactly like get_RT_CMRs itself does.
"""
import asyncio
import logging
import os
from typing import List, Optional
from urllib.parse import quote

from app.core.config import settings

logger = logging.getLogger("cmr_session_manager")

# The legacy collector detects a successful SSO login by string-matching
# this exact text in the response body -- there's no structured
# success/error response from this endpoint.
_SSO_LOGIN_SUCCESS_MARKER = "Success. Loading..."

_CURL_TIMEOUT_SECONDS = 60


async def _run_curl(url: str, extra_args: List[str]) -> Optional[str]:
    """
    Run curl against `url` and return its stdout, or None on any failure
    (non-zero exit, timeout, curl not installed). -k matches the legacy
    collector's own usage (this SSO server's cert has tripped up outdated
    CA bundles before -- see get_RT_CMRs/authenticate.cgi history) and
    matches settings.HTTPX_OPTS's verify=False used elsewhere in this app
    for the same endpoints.
    """
    try:
        proc = await asyncio.create_subprocess_exec(
            "curl", "-sk", "--max-time", str(_CURL_TIMEOUT_SECONDS), *extra_args, url,
            stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
        )
        stdout, stderr = await asyncio.wait_for(
            proc.communicate(), timeout=_CURL_TIMEOUT_SECONDS + 5
        )
        if proc.returncode != 0:
            logger.warning(
                f"curl {url.split('?')[0]}: rc={proc.returncode} "
                f"{stderr.decode(errors='ignore').strip()[:200]}"
            )
            return None
        return stdout.decode(errors="ignore")
    except Exception as e:
        logger.error(f"curl {url.split('?')[0]}: {type(e).__name__}: {e}", exc_info=True)
        return None


async def login_and_capture_session(username: str, password: str) -> bool:
    """
    One-shot login via real curl, mirroring get_RT_CMRs's own two calls:
      1. auth.int.untd.com/bin/sso?...&type=login&username=&password=
         -c <cookie jar>
      2. curl <Phantom front door> -b <cookie jar> -c <cookie jar>
    curl writes the Netscape-format cookie file directly at each step, so
    no separate cookie-saving code is needed on the Python side. Returns
    True on success, False on any failure -- never raises, so a bad
    credential just means "CMR fetch stays skipped this time", not a crash.
    """
    if not settings.cmr_cookie_jar_path:
        logger.error("login_and_capture_session: CMR_COOKIE_JAR_PATH not configured")
        return False

    directory = os.path.dirname(settings.cmr_cookie_jar_path)
    if directory:
        os.makedirs(directory, exist_ok=True)

    login_url = (
        f"{settings.sso_server_url}?async=true&action=parms&type=login"
        f"&username={quote(username, safe='')}"
        f"&password={quote(password, safe='')}"
        f"&origin_name={quote(settings.cmr_sso_origin_name, safe='')}"
        f"&origin_id={quote(settings.cmr_sso_origin_id, safe='')}"
        f"&origin_url={quote(settings.cmr_sso_origin_url, safe='')}"
    )
    login_out = await _run_curl(login_url, ["-c", settings.cmr_cookie_jar_path])
    if login_out is None:
        return False

    if _SSO_LOGIN_SUCCESS_MARKER not in login_out:
        # Safe to log: this is the SSO server's own response text, not the
        # submitted credential. Truncated since some SSO error pages can
        # be large HTML documents.
        logger.warning(
            "CMR session login: SSO did not return the expected success "
            "marker -- likely a wrong username/password, or this SSO "
            f"server doesn't accept type=login for this origin. Response "
            f"starts: {login_out[:300]!r}"
        )
        return False

    # Present the SSO cookie to Phantom's own front door once -- this is
    # the step that (per the legacy source's observed behavior) gets
    # Phantom to hand back its own session cookie, appended into the same
    # cookie file.
    phantom_out = await _run_curl(
        settings.cmr_url,
        ["-b", settings.cmr_cookie_jar_path, "-c", settings.cmr_cookie_jar_path],
    )
    if phantom_out is None:
        logger.warning(
            "CMR session login: SSO login succeeded but the Phantom "
            "front-door visit failed -- session may be incomplete"
        )
        return False

    logger.info(f"CMR session established, saved to {settings.cmr_cookie_jar_path}")
    return True
