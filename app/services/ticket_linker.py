"""
Ticket Linker Service - RT & CMR Integration
Uses:
  fim.rt_ticket_cache   — global RT ticket cache (TTL-based, keyed by ticket_id)
  fim.report_tickets    — per-report/agent ticket associations
NOTE: SSOManager is inbound-only (verifies user tokens).
      For outbound RT/CMR calls we pass the user's Bearer token directly.
      The 'token' parameter in all public methods is the raw SSO token
      extracted from the Authorization header in the API layer.
"""
import logging
import httpx
import os
import re
import subprocess
import json
import base64
import http.cookiejar
from datetime import datetime, timedelta, date
from typing import List, Dict, Tuple, Set, Optional, Optional, List, Dict
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import text
from bs4 import BeautifulSoup

from app.core.config import settings

logger = logging.getLogger("ticket_linker")

# Sourced from Settings (app/core/config.py) so these are .env-configurable
# instead of baked into source; defaults there match the original hardcoded
# values, so this is a no-op unless overridden.
RT_LOOKUP_URL = settings.rt_lookup_url
RT_UPDATE_URL = settings.rt_update_url
RT_EMAIL      = settings.rt_email
FIM_EMAIL_DOMAIN = "corp.untd.com"
CMR_URL       = settings.cmr_url
HTTPX_OPTS    = dict(verify=False, timeout=10.0)
RT_CACHE_TTL_HOURS = 1


def _username_from_token(token: str) -> str:
    """Extract username from JWT token payload (no verification needed,
    token was already verified by SSOManager on inbound)."""
    try:
        payload_b64 = token.split(".")[1]
        # Fix padding
        payload_b64 += "=" * (4 - len(payload_b64) % 4)
        payload = json.loads(base64.urlsafe_b64decode(payload_b64))
        return payload.get("username", "fim-system")
    except Exception:
        return "fim-system"


class TicketLinkerService:

    # ── RT cache helpers ──────────────────────────────────────────────────────

    @staticmethod
    async def _get_cached_rt_ticket(ticket_id: str, db: AsyncSession) -> Optional[Dict]:
        res = await db.execute(text("""
            SELECT ticket_id, subject, status, queue, ticket_data
            FROM fim.rt_ticket_cache
            WHERE ticket_id = :tid AND expires_at > NOW()
        """), {"tid": ticket_id})
        row = res.fetchone()
        if row:
            return {
                "ticket_id": row.ticket_id,
                "subject":   row.subject,
                "status":    row.status,
                "queue":     row.queue,
                "url":       f"{RT_UPDATE_URL}/ticket/{row.ticket_id}/show",
            }
        return None

    @staticmethod
    async def _cache_rt_ticket(ticket_id: str, subject: str, status: str,
                                keywords: List[str], db: AsyncSession):
        expires = datetime.utcnow() + timedelta(hours=RT_CACHE_TTL_HOURS)
        await db.execute(text("""
            INSERT INTO fim.rt_ticket_cache
                (ticket_id, subject, status, keywords, cached_at, expires_at)
            VALUES (:tid, :subj, :st, :kw, NOW(), :exp)
            ON CONFLICT (ticket_id) DO UPDATE
                SET subject    = EXCLUDED.subject,
                    status     = EXCLUDED.status,
                    keywords   = EXCLUDED.keywords,
                    cached_at  = NOW(),
                    expires_at = EXCLUDED.expires_at
        """), {
            "tid":  ticket_id,
            "subj": subject,
            "st":   status,
            "kw":   keywords,
            "exp":  expires,
        })

    # ── RT ticket subject lookup ─────────────────────────────────────────────

    @staticmethod
    async def lookup_rt_subject(ticket_id: str, token: str) -> str:
        """Look up the subject of an RT ticket by ID. Returns subject or empty string."""
        if not ticket_id or not str(ticket_id).strip().isdigit():
            return ""
        try:
            async with httpx.AsyncClient(**HTTPX_OPTS) as client:
                resp = await client.get(RT_LOOKUP_URL, params={
                    "query": f"id={ticket_id}", "sso_token": token
                })
                if resp.status_code == 200 and ":" in resp.text:
                    # Response format: "587650: Testing on test06.hyd.int.untd.com"
                    parts = resp.text.strip().split(":", 1)
                    if len(parts) == 2 and parts[0].strip().isdigit():
                        return parts[1].strip()
        except Exception as e:
            logger.error(f"lookup_rt_subject({ticket_id}): {e}")
        return ""

    # ── RT search ────────────────────────────────────────────────────────────

    @staticmethod
    async def find_daily_review_ticket(report_date, token: str) -> Optional[str]:
        """Find the daily FIM review RT ticket by exact date subject."""
        date_str = report_date.strftime("%Y/%m/%d")
        query    = f"Subject = 'Daily FIM Log Security Review - {date_str}'"
        try:
            async with httpx.AsyncClient(**HTTPX_OPTS) as client:
                resp = await client.get(RT_LOOKUP_URL, params={
                    "query": query, "sso_token": token
                })
                if resp.status_code == 200 and ":" in resp.text:
                    ticket_id = resp.text.split(":", 1)[0].strip()
                    if ticket_id.isdigit():
                        return ticket_id
        except Exception as e:
            logger.error(f"find_daily_review_ticket: {e}")
        return None

    @staticmethod
    async def search_rt_by_hostname(hostname: str, token: str,
                                    days_back: int = 7,
                                    db: AsyncSession = None) -> List[Dict]:
        """
        Search RT for tickets mentioning a hostname.
        Checks cache first, falls back to live RT API.

        Matches on Created OR LastUpdated within days_back, not Created
        alone -- an old ticket that a human recently commented on (the
        common case: work landed on a ticket opened months ago, not a
        fresh one) previously fell outside the window entirely and was
        never found, no matter how current the actual activity was.
        LastUpdated covers any touch to the ticket -- comment,
        correspondence, status change -- not just the original creation.
        """
        results    = []
        short_host = hostname.split(".")[0]

        # Check cache first
        if db:
            cache_res = await db.execute(text("""
                SELECT ticket_id, subject, status, queue
                FROM fim.rt_ticket_cache
                WHERE :host = ANY(keywords) AND expires_at > NOW()
                ORDER BY cached_at DESC
            """), {"host": short_host})
            cached = cache_res.fetchall()
            if cached:
                return [
                    {
                        "ticket_id": r.ticket_id,
                        "subject":   r.subject,
                        "status":    r.status,
                        "url":       f"{RT_UPDATE_URL}/ticket/{r.ticket_id}/show",
                        "source":    "cache",
                    }
                    for r in cached
                ]

        # Live RT search
        query = (
            f"Subject LIKE '%{short_host}%' AND "
            f"(Created > '-{days_back} days' OR LastUpdated > '-{days_back} days')"
        )
        try:
            async with httpx.AsyncClient(**HTTPX_OPTS) as client:
                resp = await client.get(RT_LOOKUP_URL, params={
                    "query": query, "format": "s", "sso_token": token
                })
                if resp.status_code != 200:
                    return results

                for line in resp.text.strip().splitlines():
                    line = line.strip()
                    if not line or line.startswith("#"):
                        continue
                    match = re.match(r"^(\d+):\s*(.+)$", line)
                    if match:
                        tid, subj = match.group(1), match.group(2)
                        results.append({
                            "ticket_id": tid,
                            "subject":   subj,
                            "status":    "open",
                            "url":       f"{RT_UPDATE_URL}/ticket/{tid}/show",
                            "source":    "rt",
                        })
                        if db:
                            await TicketLinkerService._cache_rt_ticket(
                                tid, subj, "open", [short_host, hostname], db
                            )
        except Exception as e:
            logger.error(f"search_rt_by_hostname({hostname}): {e}")

        return results

    # ── CMR search ───────────────────────────────────────────────────────────

    @staticmethod
    async def search_cmr_by_hostname(hostname: str, token: str) -> List[Dict]:
        """Search CMR (Phantom) for change records mentioning a hostname."""
        results = []
        try:
            async with httpx.AsyncClient(**HTTPX_OPTS) as client:
                resp = await client.get(CMR_URL, params={
                    "action":    "display",
                    "type":      "runadvancedsearch",
                    "hostname":  hostname,
                    "sso_token": token,
                })
                if resp.status_code == 200:
                    for cid in set(re.findall(r"#(\d{6})", resp.text)):
                        results.append({
                            "ticket_id": cid,
                            "subject":   f"CMR #{cid}",
                            "status":    "open",
                            "url":       f"{CMR_URL}?id={cid}",
                            "source":    "cmr",
                        })
        except Exception as e:
            logger.error(f"search_cmr_by_hostname({hostname}): {e}")
        return results

    # ── JIRA search ──────────────────────────────────────────────────────────

    @staticmethod
    async def search_jira_by_hostname(hostname: str, days_back: int = 7) -> List[Dict]:
        """
        Search JIRA for issues mentioning a hostname. No-op (returns []) if
        settings.jira_url isn't configured — JIRA is optional, unlike RT/CMR.
        Auth: Basic (email+token) if jira_email is set, else Bearer token —
        covers both JIRA Cloud and Server/Data Center PAT-style auth; confirm
        which matches your instance before relying on this.
        """
        if not settings.jira_url:
            return []

        results = []
        auth = None
        headers = {}
        if settings.jira_email:
            auth = (settings.jira_email, settings.jira_api_token)
        elif settings.jira_api_token:
            headers["Authorization"] = f"Bearer {settings.jira_api_token}"

        jql = f'text ~ "{hostname}" AND created >= -{days_back}d ORDER BY created DESC'
        try:
            async with httpx.AsyncClient(**HTTPX_OPTS) as client:
                resp = await client.get(
                    f"{settings.jira_url.rstrip('/')}/rest/api/2/search",
                    params={"jql": jql, "maxResults": 20, "fields": "summary,status"},
                    auth=auth,
                    headers=headers,
                )
                if resp.status_code == 200:
                    for issue in resp.json().get("issues", []):
                        key = issue.get("key")
                        fields = issue.get("fields", {}) or {}
                        results.append({
                            "ticket_id": key,
                            "subject":   fields.get("summary", ""),
                            "status":    (fields.get("status") or {}).get("name", "open"),
                            "url":       f"{settings.jira_url.rstrip('/')}/browse/{key}",
                            "source":    "jira",
                        })
                else:
                    logger.warning(
                        f"search_jira_by_hostname({hostname}): HTTP {resp.status_code}"
                    )
        except Exception as e:
            logger.error(f"search_jira_by_hostname({hostname}): {e}")
        return results

    # ── Recent activity (Reports page widget) ───────────────────────────────
    # Not scoped to any one hostname -- "what's happened fleet-wide lately",
    # for the Reports list page rather than a specific report/agent.

    @staticmethod
    async def search_rt_recent_production_tickets(token: str, days_back: int = 5) -> List[Dict]:
        """
        All tickets in the Production Systems queue touched in the last
        days_back days. Created-OR-LastUpdated, same reasoning as
        search_rt_by_hostname -- an old ticket someone just updated should
        still show up. Query shape matches the existing get_RT_CMRs cron
        job's own (confirmed-working) Queue/LastUpdated query.
        """
        query = (
            "Queue = 'Production Systems' AND "
            f"(Created > '-{days_back} days' OR LastUpdated > '-{days_back} days')"
        )
        results = []
        try:
            async with httpx.AsyncClient(**HTTPX_OPTS) as client:
                resp = await client.get(RT_LOOKUP_URL, params={
                    "query": query, "format": "s", "sso_token": token
                })
                if resp.status_code != 200:
                    logger.warning(
                        f"search_rt_recent_production_tickets: HTTP {resp.status_code}"
                    )
                    return results
                for line in resp.text.strip().splitlines():
                    line = line.strip()
                    if not line or line.startswith("#"):
                        continue
                    match = re.match(r"^(\d+):\s*(.+)$", line)
                    if match:
                        tid, subj = match.group(1), match.group(2)
                        results.append({
                            "ticket_id": tid,
                            "subject":   subj,
                            "url":       f"{RT_UPDATE_URL}/ticket/{tid}/show",
                        })
        except Exception as e:
            logger.error(f"search_rt_recent_production_tickets: {e}")
        return results

    @staticmethod
    def _load_cmr_cookies() -> Optional[Dict[str, str]]:
        """
        Load whatever's currently valid from settings.cmr_cookie_jar_path
        (Netscape cookie-file format -- curl's -b/-c format, e.g. the
        get_RT_CMRs script's phantomid.txt). Returns None if unconfigured,
        missing, unreadable, or fully expired -- callers must treat that
        as "skip CMR", not an error.
        """
        path = settings.cmr_cookie_jar_path
        if not path or not os.path.exists(path):
            return None
        jar = http.cookiejar.MozillaCookieJar(path)
        try:
            # ignore_discard=True: the SSO session cookie is marked
            # discard-on-browser-close in the file, but there's no browser
            # session here to discard it from -- we want it regardless.
            # ignore_expires=True: the real cookie file's SSO cookie uses
            # expiration "0" to mean "session cookie, no fixed expiry" (the
            # normal Netscape-format convention) -- but Python's
            # MozillaCookieJar treats a literal 0 as an already-expired
            # epoch-0 timestamp and silently drops it if ignore_expires is
            # left False, which was confirmed dropping the one cookie this
            # whole feature actually needs. Filtering genuinely-expired
            # cookies is done manually below instead, where "expires" can
            # be told apart from "no expiry recorded".
            jar.load(ignore_discard=True, ignore_expires=True)
        except Exception as e:
            logger.error(f"Failed to load CMR cookie jar {path}: {e}")
            return None
        now = datetime.now().timestamp()
        cookies = {
            c.name: c.value
            for c in jar
            if not c.expires or c.expires > now
        }
        return cookies or None

    @staticmethod
    async def fetch_recent_implemented_cmrs(days_back: int = 5) -> List[Dict]:
        """
        CMRs implemented in the last days_back days, via Phantom's own
        search UI -- Phantom has no service-account/API option, only its
        web UI behind interactive company SSO (see
        docs/PRODUCTION_DEPLOYMENT.md). Reuses whatever session is
        currently valid in settings.cmr_cookie_jar_path, an
        externally-maintained cookie jar (see get_RT_CMRs) -- NOT a
        credential FIM owns. Returns [] silently (not an error) if that
        jar is unconfigured, unreadable, or its session has expired.
        """
        cookies = TicketLinkerService._load_cmr_cookies()
        if not cookies:
            logger.info(
                "fetch_recent_implemented_cmrs: no valid CMR session cookie -- skipping"
            )
            return []

        today = date.today()
        start = today - timedelta(days=days_back)
        params = {
            "action": "display",
            "type": "runadvancedsearch",
            "mode": "prod",
            "frame": "content",
            "IMPLEMENTATION_ENDDATE": f"between '{start.isoformat()}' and '{today.isoformat()}'",
            "Status": "'Implemented'",
        }
        try:
            async with httpx.AsyncClient(**HTTPX_OPTS, cookies=cookies) as client:
                resp = await client.get(CMR_URL, params=params)
                if resp.status_code != 200:
                    logger.warning(f"fetch_recent_implemented_cmrs: HTTP {resp.status_code}")
                    return []
                return TicketLinkerService._parse_cmr_results(resp.text)
        except Exception as e:
            logger.error(f"fetch_recent_implemented_cmrs: {e}")
            return []

    @staticmethod
    def _parse_cmr_results(html: str) -> List[Dict]:
        """
        UNVERIFIED against a real authenticated response -- built from the
        column order (Request ID, Owner, Status, StartTime, Description)
        shown as the desired display, not a confirmed sample of Phantom's
        actual results HTML. Expects a standard table; a row only counts
        as a real CMR if its first cell looks like a ticket number
        ("#123456" or "123456"), which is how header/spacer rows get
        skipped. This WILL need adjusting against a real response before
        it can be trusted -- flagged deliberately rather than presented
        as verified.
        """
        results = []
        try:
            soup = BeautifulSoup(html, "html.parser")
            for row in soup.find_all("tr"):
                cells = [c.get_text(strip=True) for c in row.find_all(["td", "th"])]
                if len(cells) < 5:
                    continue
                id_match = re.match(r"^#?(\d{5,7})$", cells[0])
                if not id_match:
                    continue
                results.append({
                    "ticket_id":   id_match.group(1),
                    "owner":       cells[1],
                    "status":      cells[2],
                    "start_time":  cells[3],
                    "description": cells[4],
                    "url": (
                        f"{CMR_URL}?action=display&type=viewrequest"
                        f"&mode=prod&id={id_match.group(1)}"
                    ),
                    "source": "cmr",
                })
        except Exception as e:
            logger.error(f"_parse_cmr_results: {e}")
        return results

    # ── report_tickets helpers ────────────────────────────────────────────────

    @staticmethod
    async def _upsert_report_ticket(report_id: str, hostname: str,
                                     source: str, ticket: Dict,
                                     db: AsyncSession):
        await db.execute(text("""
            INSERT INTO fim.report_tickets
                (report_id, agent_hostname, source, external_id, summary, url)
            VALUES (:rid, :host, :src, :eid, :summ, :url)
            ON CONFLICT DO NOTHING
        """), {
            "rid":  report_id,
            "host": hostname,
            "src":  source,
            "eid":  ticket["ticket_id"],
            "summ": ticket.get("subject"),
            "url":  ticket.get("url"),
        })

    # ── High-level correlation workflow ──────────────────────────────────────

    @staticmethod
    async def correlate_all_agents(report_id: str, agent_list: List[str],
                                   token: str, db: AsyncSession) -> Dict:
        """
        For every agent:
          1. Search RT (cache then live) for hostname matches
          2. Search CMR for hostname matches
          3. Store all results in fim.report_tickets
          4. Upsert fim.report_agents with best auto-match
        token: raw SSO token from the user's Authorization header
        """
        summary = {
            "agents_processed": 0, "rt_found": 0, "cmr_found": 0, "jira_found": 0,
            "errors": [],
        }

        for hostname in agent_list:
            try:
                rt_tickets  = await TicketLinkerService.search_rt_by_hostname(
                    hostname, token, db=db
                )
                cmr_tickets = await TicketLinkerService.search_cmr_by_hostname(
                    hostname, token
                )
                jira_tickets = await TicketLinkerService.search_jira_by_hostname(hostname)

                for t in rt_tickets:
                    await TicketLinkerService._upsert_report_ticket(
                        report_id, hostname, "rt", t, db
                    )
                for t in cmr_tickets:
                    await TicketLinkerService._upsert_report_ticket(
                        report_id, hostname, "cmr", t, db
                    )
                for t in jira_tickets:
                    await TicketLinkerService._upsert_report_ticket(
                        report_id, hostname, "jira", t, db
                    )

                best_rt  = rt_tickets[0]["ticket_id"]  if rt_tickets  else None
                best_cmr = cmr_tickets[0]["ticket_id"] if cmr_tickets else None
                # NOTE: no correlated_jira column on fim.report_agents yet
                # (would need a migration — deferred to Phase 0/Alembic).
                # JIRA matches still land in fim.report_tickets above, just
                # without a "best auto-match" summary field for now.
                status   = "correlated" if (best_rt or best_cmr) else "pending"

                await db.execute(text("""
                    INSERT INTO fim.report_agents
                        (report_id, agent_hostname, correlated_rt, correlated_cmr,
                         status, correlated_at)
                    VALUES (:rid, :host, :rt, :cmr, :status, NOW())
                    ON CONFLICT (report_id, agent_hostname) DO UPDATE
                        SET correlated_rt  = EXCLUDED.correlated_rt,
                            correlated_cmr = EXCLUDED.correlated_cmr,
                            status         = EXCLUDED.status,
                            correlated_at  = NOW()
                """), {
                    "rid":    report_id,
                    "host":   hostname,
                    "rt":     best_rt,
                    "cmr":    best_cmr,
                    "status": status,
                })

                summary["agents_processed"] += 1
                if best_rt:  summary["rt_found"]  += 1
                if best_cmr: summary["cmr_found"] += 1
                if jira_tickets: summary["jira_found"] += 1

            except Exception as e:
                logger.error(f"correlate_all_agents – {hostname}: {e}")
                summary["errors"].append({"hostname": hostname, "error": str(e)})

        await db.execute(text("""
            UPDATE fim.reports
            SET correlation_run_at = NOW(),
                agents_total       = :total
            WHERE id = :rid
        """), {"rid": report_id, "total": len(agent_list)})
        await db.commit()
        return summary

    @staticmethod
    async def find_tickets_for_agent(report_id: str, hostname: str,
                                     token: str, db: AsyncSession) -> Dict:
        """On-demand refresh for a single agent."""
        rt_tickets   = await TicketLinkerService.search_rt_by_hostname(
            hostname, token, db=db
        )
        cmr_tickets  = await TicketLinkerService.search_cmr_by_hostname(hostname, token)
        jira_tickets = await TicketLinkerService.search_jira_by_hostname(hostname)

        for t in rt_tickets:
            await TicketLinkerService._upsert_report_ticket(
                report_id, hostname, "rt", t, db
            )
        for t in cmr_tickets:
            await TicketLinkerService._upsert_report_ticket(
                report_id, hostname, "cmr", t, db
            )
        for t in jira_tickets:
            await TicketLinkerService._upsert_report_ticket(
                report_id, hostname, "jira", t, db
            )
        await db.commit()
        return {"rt": rt_tickets, "cmr": cmr_tickets, "jira": jira_tickets}

    # ── RT write operations ───────────────────────────────────────────────────

    @staticmethod
    async def post_review_to_rt(ticket_id: str, subject: str,
                                content: str, token: str) -> bool:
        """Post a comment to RT via sendmail."""
        username  = _username_from_token(token)
        from_addr = f"{username}@{FIM_EMAIL_DOMAIN}"
        # Resolve email from $FIM_HOME/email_map.conf (SSO username may differ)
        try:
            with open(f"{os.environ.get('FIM_HOME', '/opt/fim')}/email_map.conf") as mf:
                for mline in mf:
                    mline = mline.strip()
                    if mline.startswith(f"{username}="):
                        from_addr = mline.split("=", 1)[1]
                        break
        except Exception:
            pass

        email_msg = (
            f"Subject: [RT #{ticket_id}] {subject}\n"
            f"From: {from_addr}\n"
            f"To: {RT_EMAIL}\n"
            f"Content-Type: text/plain; charset=UTF-8\n"
            f"\n"
            f"{content}"
        )
        try:
            result = subprocess.run(
                ["/usr/sbin/sendmail", "-t", "-f", from_addr],
                input=email_msg, capture_output=True, text=True, timeout=15)
            if result.returncode == 0:
                logger.info(f"post_review_to_rt ticket={ticket_id} from={from_addr} OK")
                return True
            else:
                logger.error(f"post_review_to_rt FAILED ticket={ticket_id} rc={result.returncode}")
        except Exception as e:
            logger.error(f"post_review_to_rt({ticket_id}): {e}")
        return False

    @staticmethod
    async def resolve_rt_ticket(ticket_id: str, token: str) -> bool:
        url = f"{RT_UPDATE_URL}/ticket/{ticket_id}/edit"
        try:
            async with httpx.AsyncClient(**HTTPX_OPTS) as client:
                resp = await client.post(
                    url,
                    data={"content": "Status: resolved\nCF-Task Type: Security Review"},
                    params={"sso_token": token},
                )
                return "updated" in resp.text.lower() or resp.status_code == 200
        except Exception as e:
            logger.error(f"resolve_rt_ticket({ticket_id}): {e}")
            return False

    # ── Publish ───────────────────────────────────────────────────────────────

    @staticmethod
    async def _resolve_rt_subjects(agents_data: List[Dict], token: str) -> Dict[str, str]:
        """
        Collect all unique RT ticket IDs from agents_data and look up their
        subjects from the RT API. Returns {ticket_id: subject}.
        """
        rt_ids = set()
        for a in agents_data:
            for field in ("manual_rt", "correlated_rt"):
                tid = a.get(field)
                if tid and str(tid).strip().isdigit():
                    rt_ids.add(str(tid).strip())

        subjects = {}
        for tid in rt_ids:
            subj = await TicketLinkerService.lookup_rt_subject(tid, token)
            if subj:
                subjects[tid] = subj
        return subjects

    @staticmethod
    def _build_publish_content(report_date, agents_data: List[Dict],
                               analyst_notes: str = "",
                               rt_subjects: Dict[str, str] = None) -> str:
        if rt_subjects is None:
            rt_subjects = {}

        lines = [
            f"FIM Daily Security Review — {report_date}",
            "=" * 70,
            f"Published: {datetime.utcnow().strftime('%Y-%m-%d %H:%M UTC')}",
        ]

        # Report-level analyst notes
        if analyst_notes:
            lines += ["", f"Analyst Notes: {analyst_notes}"]

        # Summary counts
        total_agents  = len(agents_data)
        total_changes = sum(a.get("change_count", 0) for a in agents_data)
        lines += [
            "",
            f"Total Agents: {total_agents}   |   Total Changes: {total_changes}",
            "-" * 70,
        ]

        for a in agents_data:
            hostname = a.get("agent_hostname", "unknown")
            status   = a.get("status", "pending")
            count    = a.get("change_count", 0)
            note     = a.get("correlation_note") or ""

            # Determine RT reference with subject
            rt_num = a.get("manual_rt") or a.get("correlated_rt") or None
            if rt_num:
                rt_subj = rt_subjects.get(str(rt_num), "")
                rt_display = f"RT#{rt_num} — {rt_subj}" if rt_subj else f"RT#{rt_num}"
            else:
                rt_display = "N/A"

            cmr_num = a.get("correlated_cmr") or None
            cmr_display = f"CMR#{cmr_num}" if cmr_num else "N/A"

            lines += [
                "",
                f"HOST: {hostname}",
                f"  Review Status : {status}",
                f"  Changes       : {count}",
                f"  RT Ticket     : {rt_display}",
                f"  CMR           : {cmr_display}",
            ]
            if note:
                lines.append(f"  Note          : {note}")

            # Individual change details
            changes = a.get("changes", [])
            if changes:
                lines.append("")
                lines.append(f"  {'Type':<10}  {'Severity':<8}  {'File Path'}")
                lines.append(f"  {'-'*10}  {'-'*8}  {'-'*50}")
                for ch in changes:
                    ctype    = (ch.get("change_type") or "unknown").upper()
                    severity = (ch.get("severity") or "medium").upper()
                    fpath    = ch.get("file_path", "unknown")
                    lines.append(f"  {ctype:<10}  {severity:<8}  {fpath}")

                    # Show hash info if available
                    bh      = ch.get("baseline_hash") or ""
                    ch_hash = ch.get("current_hash") or ""
                    if bh and ch_hash and bh != ch_hash:
                        lines.append(f"  {'':10}  {'':8}  hash: {bh[:16]}... -> {ch_hash[:16]}...")
                    elif ch_hash and not bh:
                        lines.append(f"  {'':10}  {'':8}  hash: {ch_hash[:16]}...")

                    # Show size info
                    bs = ch.get("baseline_size")
                    cs = ch.get("current_size")
                    if cs is not None:
                        if bs is not None and bs != cs:
                            lines.append(f"  {'':10}  {'':8}  size: {bs} -> {cs} bytes")
                        else:
                            lines.append(f"  {'':10}  {'':8}  size: {cs} bytes")

                    # Show per-change analyst notes
                    ch_notes = ch.get("analyst_notes")
                    if ch_notes:
                        lines.append(f"  {'':10}  {'':8}  note: {ch_notes}")

                    # Flags
                    flags = []
                    if ch.get("is_known_change"):
                        flags.append("KNOWN")
                    if ch.get("requires_investigation"):
                        flags.append("INVESTIGATE")
                    if flags:
                        lines.append(f"  {'':10}  {'':8}  flags: [{', '.join(flags)}]")

            lines.append("")

        lines += [
            "-" * 70,
            "Generated by FIM Enterprise — automated security review system",
        ]
        return "\n".join(lines)

    @staticmethod
    async def publish_report(report_id: str, report_date,
                             agents_data: List[Dict], token: str,
                             analyst_notes: str = "") -> Dict:
        """
        Find the daily RT review ticket and post the FIM summary as a comment.
        token: raw SSO token from the user's Authorization header
        Returns: {success, ticket_id, message, status_to_set}
        """
        ticket_id = await TicketLinkerService.find_daily_review_ticket(
            report_date, token
        )
        if not ticket_id:
            return {
                "success":       False,
                "ticket_id":     None,
                "status_to_set": "submitted_no_ticket",
                "message": (
                    f"No RT ticket found for 'Daily FIM Log Security Review - "
                    f"{report_date.strftime('%Y/%m/%d')}'. "
                    f"Report marked as submitted_no_ticket."
                ),
            }

        # Look up RT ticket subjects for referenced tickets
        rt_subjects = await TicketLinkerService._resolve_rt_subjects(agents_data, token)

        subject = f"Daily FIM Log Security Review - {report_date.strftime('%Y/%m/%d')}"
        content = TicketLinkerService._build_publish_content(
            report_date, agents_data,
            analyst_notes=analyst_notes,
            rt_subjects=rt_subjects,
        )
        posted = await TicketLinkerService.post_review_to_rt(
            ticket_id, subject, content, token
        )

        return {
            "success":       posted,
            "ticket_id":     ticket_id,
            "status_to_set": "submitted" if posted else "in_review",
            "message": (
                f"Published to RT ticket #{ticket_id}" if posted
                else f"Found RT ticket #{ticket_id} but failed to post comment."
            ),
        }
