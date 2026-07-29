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
from datetime import datetime, timedelta
from typing import List, Dict, Tuple, Set, Optional, Optional, List, Dict
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import text

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
        query = f"Subject LIKE '%{short_host}%' AND Created > '-{days_back} days'"
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
