"""
Email Notification Service

Sends notifications via local sendmail for:
  - Daily report auto-generated (to analysts)
  - Critical alerts detected
  - Baseline integrity failures

Uses /usr/sbin/sendmail (same as RT integration).
"""
import subprocess
import logging
from datetime import datetime
from typing import List, Dict, Tuple, Set, Optional, List, Optional

logger = logging.getLogger("email_service")

DEFAULT_FROM = "fim-noreply@untd.com"


class EmailService:

    @staticmethod
    def send_email(to: List[str], subject: str, body: str, from_addr: str = DEFAULT_FROM) -> bool:
        """Send email via sendmail."""
        if not to:
            logger.warning("No recipients for email")
            return False

        message = f"""From: FIM Enterprise <{from_addr}>
To: {', '.join(to)}
Subject: {subject}
Content-Type: text/plain; charset=utf-8
X-Mailer: FIM-Enterprise/1.0

{body}
"""
        try:
            proc = subprocess.run(
                ["/usr/sbin/sendmail", "-t", "-f", from_addr],
                input=message.encode("utf-8"),
                capture_output=True, timeout=30
            )
            if proc.returncode == 0:
                logger.info(f"Email sent: to={to} subject={subject}")
                return True
            else:
                logger.error(f"sendmail failed: {proc.stderr.decode()}")
                return False
        except Exception as e:
            logger.error(f"Email error: {e}")
            return False

    @staticmethod
    def notify_report_generated(report_date: str, agents: int, alerts: int, recipients: List[str]):
        """Notify analysts that a daily report has been auto-generated."""
        subject = f"[FIM] Daily Report Generated — {report_date}"
        body = f"""FIM Daily Report Auto-Generated
================================

Report Date : {report_date}
Agents      : {agents}
Alerts      : {alerts}
Generated   : {datetime.now().strftime('%Y-%m-%d %H:%M IST')}

Action Required:
  - Review changes for each agent
  - Submit agent reviews
  - Publish to RT when complete

Dashboard: http://test06.hyd.int.untd.com/reports

---
This is an automated notification from FIM Enterprise.
"""
        return EmailService.send_email(recipients, subject, body)

    @staticmethod
    def notify_critical_alert(hostname: str, file_path: str, alert_type: str, recipients: List[str]):
        """Notify on critical severity alerts."""
        subject = f"[FIM CRITICAL] {alert_type} on {hostname}"
        body = f"""CRITICAL FIM Alert
==================

Host      : {hostname}
File      : {file_path}
Type      : {alert_type}
Detected  : {datetime.now().strftime('%Y-%m-%d %H:%M IST')}

Immediate investigation recommended.

Dashboard: http://test06.hyd.int.untd.com/alerts

---
This is an automated notification from FIM Enterprise.
"""
        return EmailService.send_email(recipients, subject, body)

    @staticmethod
    def notify_agent_stale(hostname: str, recipients: List[str]):
        """Notify when an agent transitions to stale/offline (not repeated every hour it stays down)."""
        subject = f"[FIM] Agent offline — {hostname}"
        body = f"""FIM Agent Went Offline
======================

Host      : {hostname}
Detected  : {datetime.now().strftime('%Y-%m-%d %H:%M IST')}

This agent has stopped sending heartbeats within its expected interval.
No further scans or real-time detection are happening on this host until
it reconnects.

Dashboard: http://test06.hyd.int.untd.com/agents

---
This is an automated notification from FIM Enterprise.
"""
        return EmailService.send_email(recipients, subject, body)

    @staticmethod
    def notify_baseline_integrity_failure(agent_hostname: str, baseline_id: str, recipients: List[str]):
        """Notify on baseline integrity verification failure."""
        subject = f"[FIM SECURITY] Baseline Integrity Failure — {agent_hostname}"
        body = f"""BASELINE INTEGRITY FAILURE
==========================

Host        : {agent_hostname}
Baseline ID : {baseline_id}
Detected    : {datetime.now().strftime('%Y-%m-%d %H:%M IST')}

The baseline data does not match its stored checksum.
This could indicate database tampering.

The baseline has been automatically deactivated.
A new baseline will be created from the next scan.

INVESTIGATE IMMEDIATELY.

Dashboard: http://test06.hyd.int.untd.com/baselines

---
This is an automated notification from FIM Enterprise.
"""
        return EmailService.send_email(recipients, subject, body)
