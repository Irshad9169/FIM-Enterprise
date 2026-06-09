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
import re
from datetime import datetime, timedelta
from typing import Optional, List, Dict
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import text

logger = logging.getLogger("ticket_linker")

RT_LOOKUP_URL = "http://rtapi.int.untd.com/cgi-bin/rt.cgi"
RT_UPDATE_URL = "https://rtapi.int.untd.com/cgi-bin/rt.cgi"
CMR_URL       = "https://phantom.int.untd.com/bin/phantom"
HTTPX_OPTS    = dict(verify=False, timeout=10.0)
RT_CACHE_TTL_HOURS = 1


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
        summary = {"agents_processed": 0, "rt_found": 0, "cmr_found": 0, "errors": []}

        for hostname in agent_list:
            try:
                rt_tickets  = await TicketLinkerService.search_rt_by_hostname(
                    hostname, token, db=db
                )
                cmr_tickets = await TicketLinkerService.search_cmr_by_hostname(
                    hostname, token
                )

                for t in rt_tickets:
                    await TicketLinkerService._upsert_report_ticket(
                        report_id, hostname, "rt", t, db
                    )
                for t in cmr_tickets:
                    await TicketLinkerService._upsert_report_ticket(
                        report_id, hostname, "cmr", t, db
                    )

                best_rt  = rt_tickets[0]["ticket_id"]  if rt_tickets  else None
                best_cmr = cmr_tickets[0]["ticket_id"] if cmr_tickets else None
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
        rt_tickets  = await TicketLinkerService.search_rt_by_hostname(
            hostname, token, db=db
        )
        cmr_tickets = await TicketLinkerService.search_cmr_by_hostname(hostname, token)

        for t in rt_tickets:
            await TicketLinkerService._upsert_report_ticket(
                report_id, hostname, "rt", t, db
            )
        for t in cmr_tickets:
            await TicketLinkerService._upsert_report_ticket(
                report_id, hostname, "cmr", t, db
            )
        await db.commit()
        return {"rt": rt_tickets, "cmr": cmr_tickets}

    # ── RT write operations ───────────────────────────────────────────────────

    @staticmethod
    async def post_review_to_rt(ticket_id: str, content: str, token: str) -> bool:
        """
        Post a comment to RT via the CGI endpoint.
        RT REST API v1 content field format:
          id: ticket/N
          Action: comment
          Text: <body with each continuation line indented by a space>
        """
        # Indent every line of the body — RT requires continuation lines start with a space
        indented_body = content.replace("\n", "\n ")
        rt_content = (
            f"id: ticket/{ticket_id}\n"
            f"Action: comment\n"
            f"Text: {indented_body}"
        )

        # Use the base CGI URL (no path suffix) — same endpoint that search uses
        url = RT_LOOKUP_URL

        try:
            async with httpx.AsyncClient(**HTTPX_OPTS) as client:
                resp = await client.post(
                    url,
                    data={"content": rt_content},
                    params={"sso_token": token},
                )
                logger.info(
                    f"post_review_to_rt ticket={ticket_id} "
                    f"status={resp.status_code} "
                    f"body={resp.text[:400]!r}"
                )
                # RT returns "# Message recorded" or "# Ticket NNN updated" on success
                if resp.status_code == 200 and (
                    "recorded" in resp.text.lower()
                    or "updated" in resp.text.lower()
                ):
                    return True
                logger.error(f"post_review_to_rt FAILED body={resp.text[:400]!r}")
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
    def _build_publish_content(report_date, agents_data: List[Dict]) -> str:
        lines = [
            f"FIM Daily Security Review — {report_date}",
            "=" * 60,
            f"Published: {datetime.utcnow().strftime('%Y-%m-%d %H:%M UTC')}",
            "",
        ]
        for a in agents_data:
            rt_num  = a.get("manual_rt") or a.get("correlated_rt") or "N/A"
            cmr_num = a.get("correlated_cmr") or "N/A"
            note    = a.get("correlation_note") or ""
            lines += [
                f"Host    : {a.get('agent_hostname', 'unknown')}",
                f"  Status  : {a.get('status', 'pending')}",
                f"  Changes : {a.get('change_count', 0)}",
                f"  RT      : {rt_num}",
                f"  CMR     : {cmr_num}",
            ]
            if note:
                lines.append(f"  Note    : {note}")
            lines.append("")
        return "\n".join(lines)

    @staticmethod
    async def publish_report(report_id: str, report_date,
                             agents_data: List[Dict], token: str) -> Dict:
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

        content = TicketLinkerService._build_publish_content(report_date, agents_data)
        posted  = await TicketLinkerService.post_review_to_rt(ticket_id, content, token)

        return {
            "success":       posted,
            "ticket_id":     ticket_id,
            "status_to_set": "submitted" if posted else "in_review",
            "message": (
                f"Published to RT ticket #{ticket_id}" if posted
                else f"Found RT ticket #{ticket_id} but failed to post comment."
            ),
        }
