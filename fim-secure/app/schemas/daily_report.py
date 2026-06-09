"""
Pydantic Schemas - aligned to actual DB schema
"""
from pydantic import BaseModel, UUID4
from datetime import date, datetime
from typing import Optional, List, Dict, Any


# ── Sub-objects ───────────────────────────────────────────────────────────────

class DailyReportSummary(BaseModel):
    added_files:   int = 0
    removed_files: int = 0
    changed_files: int = 0


class ReportChangeDetail(BaseModel):
    id:                       Optional[str] = None
    file_path:                str
    agent_hostname:           Optional[str] = None
    change_type:              Optional[str] = None
    severity:                 Optional[str] = None

    # File state
    baseline_hash:            Optional[str] = None
    current_hash:             Optional[str] = None
    baseline_size:            Optional[int] = None
    current_size:             Optional[int] = None
    baseline_mtime:           Optional[str] = None
    current_mtime:            Optional[str] = None

    # Ticket linking — mapped to real DB columns
    external_ticket_id:       Optional[str] = None      # primary RT#
    linked_rt_tickets:        List[str] = []             # confirmed RT links
    matched_rt_tickets:       Optional[Any] = None       # auto-matched (jsonb)
    rt_ticket_manually_added: bool = False

    # Review state
    analyst_notes:            Optional[str] = None
    is_known_change:          bool = False
    is_verified:              bool = False
    requires_investigation:   bool = False


class ReportTicketSchema(BaseModel):
    id:             Optional[str] = None
    source:         str                     # 'rt' | 'cmr'
    external_id:    str
    summary:        Optional[str] = None
    url:            Optional[str] = None
    is_linked:      bool = False

    class Config:
        from_attributes = True


class ReportAgentSchema(BaseModel):
    id:               Optional[str] = None
    agent_hostname:   str
    ip_address:       Optional[str] = None
    correlated_rt:    Optional[str] = None
    correlated_cmr:   Optional[str] = None
    manual_rt:        Optional[str] = None
    correlation_note: Optional[str] = None
    status:           str = "pending"
    is_skipped:       bool = False
    skip_reason:      Optional[str] = None
    correlated_at:    Optional[datetime] = None
    submitted_at:     Optional[datetime] = None
    changes:          List[ReportChangeDetail] = []
    tickets:          List[ReportTicketSchema] = []     # from report_tickets

    class Config:
        from_attributes = True


# ── Report responses ──────────────────────────────────────────────────────────

class DailyReportResponse(BaseModel):
    id:               UUID4
    report_date:      date
    agents:           List[str] = []
    summary:          DailyReportSummary
    # DB status values: pending/in_review/reviewed/submitted/submitted_no_ticket
    status:           str = "pending"
    total_changes:    int = 0
    analyst_notes:    Optional[str] = None
    created_at:       datetime
    agents_total:     int = 0
    # Derived: len(submitted_agents)
    agents_submitted: int = 0
    rt_ticket_id:     Optional[str] = None
    published_at:     Optional[datetime] = None

    class Config:
        from_attributes = True


class DailyReportDetail(DailyReportResponse):
    changes:            Dict[str, List[str]] = {"added": [], "removed": [], "changed": []}
    details:            List[ReportChangeDetail] = []
    report_agents:      List[ReportAgentSchema] = []
    correlation_run_at: Optional[datetime] = None
    submitted_agents:   List[str] = []

    class Config:
        from_attributes = True


# ── Request bodies ────────────────────────────────────────────────────────────

class GenerateReportRequest(BaseModel):
    report_date: Optional[date] = None


class UpdateNotesRequest(BaseModel):
    analyst_notes: str


class UpdateStatusRequest(BaseModel):
    # Must be one of: pending/in_review/reviewed/submitted/submitted_no_ticket
    status: str


class UpdateAgentRequest(BaseModel):
    manual_rt:        Optional[str] = None
    correlated_rt:    Optional[str] = None
    correlated_cmr:   Optional[str] = None
    correlation_note: Optional[str] = None
    is_skipped:       Optional[bool] = None
    skip_reason:      Optional[str] = None


class SubmitAgentRequest(BaseModel):
    rt_number: Optional[str] = None
    note:      Optional[str] = None


class LinkChangeRequest(BaseModel):
    """
    Link a file change to an RT ticket.
    Sets external_ticket_id and appends to linked_rt_tickets[].
    If is_known_change=True, analyst_notes is REQUIRED (DB CHECK constraint).
    """
    rt_number:        Optional[str] = None
    is_known_change:  Optional[bool] = None
    analyst_notes:    Optional[str] = None      # required when is_known_change=True
    requires_investigation: Optional[bool] = None


class PublishReportRequest(BaseModel):
    force: bool = False     # publish even if not all agents submitted
