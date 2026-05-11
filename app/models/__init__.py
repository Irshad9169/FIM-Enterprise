from app.models.models import (
    User, Agent, Policy, Alert, Baseline, AuditLog,
    AlertRule, RuleExecution, ComplianceFramework,
    ComplianceControl, PolicyControlMapping,
    ComplianceViolation, ComplianceReport, Scan,
    WhitelistRule, ScanRequest
)

# ── ADD THIS ──────────────────────────────────────────
from app.models.daily_report import (
    DailyReport, ReportChange,
    ReportAgent, ReportTicket, RTTicketCache,   # new
)
# ─────────────────────────────────────────────────────

__all__ = [
    "User", "Agent", "Policy", "Alert", "Baseline",
    "AuditLog", "AlertRule", "RuleExecution",
    "ComplianceFramework", "ComplianceControl",
    "PolicyControlMapping", "ComplianceViolation",
    "ComplianceReport", "Scan", "WhitelistRule", "ScanRequest",
    # new
    "DailyReport", "ReportChange",
    "ReportAgent", "ReportTicket", "RTTicketCache",
]
