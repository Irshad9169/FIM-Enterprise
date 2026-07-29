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

from app.core.database import db_manager
from app.models.daily_report import DailyReport, ReportChange, ReportAgent

logger = logging.getLogger("report_scheduler")

# IST is UTC+5:30
IST = timezone(timedelta(hours=5, minutes=30))

# Default: generate report at 09:00 AM IST
DEFAULT_SCHEDULE_HOUR = 9
DEFAULT_SCHEDULE_MINUTE = 0


class ReportScheduler:
    """
    Background scheduler that auto-generates daily FIM reports.

    Configure via environment variables:
      REPORT_SCHEDULE_HOUR=9      (0-23, IST)
      REPORT_SCHEDULE_MINUTE=0    (0-59)
      REPORT_AUTO_GENERATE=true   (enable/disable)
    """

    def __init__(self):
        import os
        self.enabled = os.getenv("REPORT_AUTO_GENERATE", "true").lower() in ("true", "1", "yes")
        self.hour = int(os.getenv("REPORT_SCHEDULE_HOUR", str(DEFAULT_SCHEDULE_HOUR)))
        self.minute = int(os.getenv("REPORT_SCHEDULE_MINUTE", str(DEFAULT_SCHEDULE_MINUTE)))
        self._task: asyncio.Task = None
        self._running = False

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
        logger.info(
            f"Report scheduler started — will generate daily reports at "
            f"{self.hour:02d}:{self.minute:02d} IST"
        )

    def stop(self):
        """Stop the scheduler."""
        self._running = False
        if self._task:
            self._task.cancel()
            logger.info("Report scheduler stopped")

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
                       ag.hostname, ag.ip_address
                FROM fim.alerts a
                LEFT JOIN fim.agents ag ON a.agent_id = ag.id
                WHERE DATE(a.detected_at) = :d
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
                # Get analyst emails from DB
                email_result = await db.execute(text(
                    "SELECT email FROM fim.users WHERE role IN ('admin', 'analyst') AND is_active = true"
                ))
                recipients = [row.email for row in email_result.fetchall() if row.email]
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
