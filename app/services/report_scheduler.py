"""
Daily Report Auto-Generator

Automatically generates FIM daily reports at a configured time (default 09:00 AM IST).

How it works:
  1. Runs as a background task in the FastAPI application
  2. Uses asyncio scheduler (no external dependencies like cron)
  3. At the configured time, generates a report for the PREVIOUS day
     (e.g., at 09:00 AM on Feb 21, generates report for Feb 20)
  4. Skips if a report for that date already exists
  5. Uses a system user for the generated_by field

Integration:
  Add to main.py lifespan:
    from app.services.report_scheduler import ReportScheduler
    scheduler = ReportScheduler()

    @asynccontextmanager
    async def lifespan(app):
        await db_manager.initialize()
        await scheduler.start()
        yield
        scheduler.stop()
        await db_manager.close()
"""
import asyncio
import logging
import uuid
import json
from app.services.anomaly_detector import run_anomaly_detection
from datetime import datetime, date, timedelta, time, timezone
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.database import db_manager
from app.models.daily_report import DailyReport, ReportChange, ReportAgent

logger = logging.getLogger("report_scheduler")

# IST is UTC+5:30
IST = timezone(timedelta(hours=5, minutes=30))


class ReportScheduler:
    """
    Background scheduler that auto-generates daily FIM reports.

    Configure via environment variables:
      REPORT_SCHEDULE_HOUR=9      (0-23, IST)
      REPORT_SCHEDULE_MINUTE=0    (0-59)
      REPORT_AUTO_GENERATE=true   (enable/disable)
    """

    def __init__(self):
        # Sourced from Settings (REPORT_* in .env) instead of bare
        # os.getenv() — see app/core/config.py for why.
        self.enabled = settings.report_auto_generate
        self.hour = settings.report_schedule_hour
        self.minute = settings.report_schedule_minute
        self._task: asyncio.Task = None
        self._hourly_task: asyncio.Task = None
        self._running = False

    @staticmethod
    async def _get_alert_recipients(db) -> list:
        """Admin/analyst emails — shared by _generate_report and _run_agent_health_check."""
        result = await db.execute(text(
            "SELECT email FROM fim.users WHERE role IN ('admin', 'analyst') AND is_active = true"
        ))
        return [row.email for row in result.fetchall() if row.email]

    async def _run_anomaly_detection(self):
        """GAP #19: Run anomaly detection hourly."""
        import logging
        logger = logging.getLogger(__name__)
        try:
            from app.core.database import db_manager
            async with db_manager.get_session() as db:
                anomalies = await run_anomaly_detection(db)
                if anomalies:
                    logger.warning(
                        "GAP#19: %d anomalous agent(s) detected", len(anomalies)
                    )
        except Exception as e:
            logger.error("GAP#19: Scheduled anomaly detection failed: %s", e)

    async def start(self):
        """Start the scheduler background task."""
        if not self.enabled:
            logger.info("Report auto-generation is DISABLED")
            return

        self._running = True
        self._task = asyncio.create_task(self._scheduler_loop())
        self._hourly_task = asyncio.create_task(self._hourly_loop())
        logger.info(
            f"Report scheduler started — will generate daily reports at "
            f"{self.hour:02d}:{self.minute:02d} IST"
        )

    def stop(self):
        """Stop the scheduler."""
        self._running = False
        if self._task:
            self._task.cancel()
        if self._hourly_task:
            self._hourly_task.cancel()
        logger.info("Report scheduler stopped")

    async def _hourly_loop(self):
        """
        Independent hourly loop — can't share _scheduler_loop's sleep since
        that one sleeps for up to ~24h at a stretch waiting for the daily
        report time. Runs agent health/stale-agent checking every hour.
        """
        while self._running:
            try:
                await asyncio.sleep(3600)
                if not self._running:
                    break
                await self._run_agent_health_check()
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Hourly check error: {e}", exc_info=True)
                await asyncio.sleep(60)

    async def _run_agent_health_check(self):
        """
        Item 12a: AgentHealthMonitor.update_agent_health_status already exists
        and does the right thing (flips Agent.is_healthy, returns
        went_offline/came_online transition lists) but previously had zero
        callers outside the pull-based /api/v1/agent-health/* endpoints —
        nothing ran it proactively. Emails only the went_offline list, which
        only contains a hostname at the moment it transitions to stale, not
        every hour it remains stale (update_agent_health_status already does
        this transition tracking internally — no new dedup logic needed here).
        """
        from app.services.agent_health import AgentHealthMonitor
        from app.services.email_service import EmailService

        db = db_manager.get_session()
        try:
            result = await AgentHealthMonitor.update_agent_health_status(db)
            went_offline = result.get('went_offline') or []
            if not went_offline:
                return

            recipients = await self._get_alert_recipients(db)
            if not recipients:
                return

            for hostname in went_offline:
                EmailService.notify_agent_stale(hostname, recipients)
        except Exception as e:
            logger.error(f"Agent health check failed: {e}", exc_info=True)
        finally:
            try:
                await db.close()
            except Exception:
                pass

    async def _scheduler_loop(self):
        """
        Main scheduler loop.
        Calculates seconds until the next target time and sleeps until then.
        """
        while self._running:
            try:
                now_ist = datetime.now(IST)
                target_today = now_ist.replace(
                    hour=self.hour, minute=self.minute,
                    second=0, microsecond=0
                )

                if now_ist >= target_today:
                    # Already past today's target — schedule for tomorrow
                    target = target_today + timedelta(days=1)
                else:
                    target = target_today

                wait_seconds = (target - now_ist).total_seconds()
                logger.info(
                    f"Next report generation at {target.strftime('%Y-%m-%d %H:%M IST')} "
                    f"({wait_seconds / 3600:.1f} hours from now)"
                )

                await asyncio.sleep(wait_seconds)

                if not self._running:
                    break

                # Generate report for yesterday
                report_date = (datetime.now(IST) - timedelta(days=1)).date()
                logger.info(f"Auto-generating daily report for {report_date}")

                await self._generate_report(report_date)

            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Scheduler error: {e}", exc_info=True)
                await asyncio.sleep(60)  # Retry after 1 minute

    async def _generate_report(self, report_date: date):
        """
        Generate a daily report for the given date.
        Mirrors the logic in reports.py generate_daily_report endpoint.
        """
        db = db_manager.get_session()
        try:
            # Check if report already exists
            existing = await db.execute(
                select(DailyReport).where(DailyReport.report_date == report_date)
            )
            if existing.scalar_one_or_none():
                logger.info(f"Report for {report_date} already exists — skipping")
                return

            # Fetch alerts for the day
            res = await db.execute(text("""
                SELECT a.id, a.file_path, a.alert_type, a.severity,
                       a.previous_state, a.current_state, a.detected_at,
                       a.audit_uid, a.audit_process, a.audit_command,
                       ag.hostname, ag.ip_address
                FROM fim.alerts a
                LEFT JOIN fim.agents ag ON a.agent_id = ag.id
                WHERE DATE(a.detected_at) = :d AND a.status != 'false_positive'
                ORDER BY ag.hostname, a.detected_at
            """), {"d": report_date})
            alerts = res.fetchall()

            report_id = uuid.uuid4()
            agents = list({a.hostname for a in alerts if a.hostname})

            report = DailyReport(
                id=report_id,
                report_date=report_date,
                agent_list=agents,
                submitted_agents=[],
                total_added=sum(1 for a in alerts if "created" in str(a.alert_type).lower()),
                total_removed=sum(1 for a in alerts if "deleted" in str(a.alert_type).lower()),
                total_changed=sum(1 for a in alerts if "modified" in str(a.alert_type).lower()),
                total_changes=len(alerts),
                total_servers=len(agents),
                agents_total=len(agents),
                status="pending",
                # generated_by left as None for auto-generated reports
            )
            db.add(report)
            await db.flush()

            # Create report changes
            for a in alerts:
                try:
                    p = json.loads(a.previous_state) if isinstance(a.previous_state, str) else (a.previous_state or {})
                    c = json.loads(a.current_state) if isinstance(a.current_state, str) else (a.current_state or {})
                    change = ReportChange(
                        id=uuid.uuid4(),
                        report_id=report_id,
                        alert_id=a.id,
                        agent_hostname=a.hostname or "unknown",
                        file_path=a.file_path or "unknown",
                        change_type=(
                            "added" if "created" in str(a.alert_type).lower() else
                            "removed" if "deleted" in str(a.alert_type).lower() else
                            "changed"
                        ),
                        severity=a.severity or "medium",
                        current_mtime=a.detected_at,
                        baseline_hash=p.get("hash"),
                        current_hash=c.get("hash"),
                        baseline_size=p.get("size"),
                        current_size=c.get("size"),
                        baseline_mtime=(
                            datetime.fromisoformat(str(p["mtime"]).replace("Z", "+00:00"))
                            if p.get("mtime") else None
                        ),
                        audit_uid=a.audit_uid,
                        audit_process=a.audit_process,
                        audit_command=a.audit_command,
                        content_diff=c.get("content_diff"),
                    )
                    db.add(change)
                except Exception:
                    continue

            # Create report_agents entries
            agent_ips = {}
            for a in alerts:
                if a.hostname and a.hostname not in agent_ips:
                    agent_ips[a.hostname] = a.ip_address

            for hostname in agents:
                ra = ReportAgent(
                    id=uuid.uuid4(),
                    report_id=report_id,
                    agent_hostname=hostname,
                    ip_address=agent_ips.get(hostname),
                    status="pending",
                )
                db.add(ra)

            await db.commit()
            logger.info(
                f"Auto-generated report for {report_date}: "
                f"{len(alerts)} alerts, {len(agents)} agents, "
                f"report_id={report_id}"
            )

            # Send email notification
            try:
                from app.services.email_service import EmailService
                recipients = await self._get_alert_recipients(db)
                if recipients:
                    EmailService.notify_report_generated(
                        str(report_date), len(agents), len(alerts), recipients
                    )
            except Exception as e:
                logger.warning(f"Failed to send report notification: {e}")

        except Exception as e:
            await db.rollback()
            logger.error(f"Failed to generate report for {report_date}: {e}", exc_info=True)
        finally:
            try:
                await db.close()
            except Exception:
                pass
