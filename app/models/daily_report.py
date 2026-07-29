"""
ORM Models - aligned to actual fim.* schema
"""
from sqlalchemy import (
    Column, String, Integer, BigInteger, Boolean, Text,
    DateTime, Date, ForeignKey, ARRAY
)
from sqlalchemy.dialects.postgresql import UUID, JSONB
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func
from app.core.database import Base
import uuid


class DailyReport(Base):
    __tablename__ = "reports"
    __table_args__ = {"schema": "fim"}

    id                      = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    report_type             = Column(String(20), default="daily")
    # NOTE: not actually NOT NULL/UNIQUE at the DB level today (confirmed via
    # autogenerate diff against live schema) — left un-constrained here to
    # match reality rather than risk an ALTER on existing data; app code
    # always supplies report_date regardless.
    report_date             = Column(Date)

    # Date range (custom reports)
    date_from               = Column(Date)
    date_to                 = Column(Date)

    # Change counts
    total_changes           = Column(Integer, default=0)
    total_servers           = Column(Integer, default=0)
    known_changes           = Column(Integer, default=0)
    unknown_changes         = Column(Integer, default=0)
    correlation_groups_count = Column(Integer, default=0)
    total_added             = Column(Integer, default=0)
    total_removed           = Column(Integer, default=0)
    total_changed           = Column(Integer, default=0)

    # Status — DB CHECK: pending/in_review/reviewed/submitted/submitted_no_ticket
    status                  = Column(String(20), default="pending")

    # Agent tracking
    # agent_list is text[] in DB
    agent_list              = Column(ARRAY(Text))
    # submitted_agents tracks hostnames that have been submitted
    submitted_agents        = Column(ARRAY(Text), default=list)
    # agents_total added by migration 002
    agents_total            = Column(Integer, default=0)

    # Analyst workflow
    analyst_notes           = Column(Text)

    # RT integration (all pre-existing)
    rt_ticket_searched      = Column(Boolean, default=False)
    rt_ticket_found         = Column(Boolean, default=False)
    rt_ticket_id            = Column(String(50))
    rt_ticket_url           = Column(Text)
    rt_search_error         = Column(Text)

    # Ownership (pre-existing)
    generated_by            = Column(UUID(as_uuid=True), ForeignKey("fim.users.id"))
    reviewed_by             = Column(UUID(as_uuid=True), ForeignKey("fim.users.id"))
    submitted_by            = Column(UUID(as_uuid=True), ForeignKey("fim.users.id"))

    # Timestamps (pre-existing)
    submitted_at            = Column(DateTime)
    created_at              = Column(DateTime, server_default=func.now())
    updated_at              = Column(DateTime, server_default=func.now(), onupdate=func.now())

    # Added by migration 002
    correlation_run_at      = Column(DateTime(timezone=True))
    published_at            = Column(DateTime(timezone=True))
    published_by            = Column(UUID(as_uuid=True))

    # Relationships
    changes                 = relationship("ReportChange", back_populates="report",
                                           cascade="all, delete-orphan")
    report_agents           = relationship("ReportAgent", back_populates="report",
                                           cascade="all, delete-orphan")
    tickets                 = relationship("ReportTicket", back_populates="report",
                                           cascade="all, delete-orphan")


class ReportChange(Base):
    """
    Maps to fim.report_changes — use all existing columns.
    Key columns:
      external_ticket_id      → primary RT # for this change
      linked_rt_tickets       → text[] of confirmed linked RT tickets
      rt_ticket_manually_added→ true when analyst manually adds a ticket
      analyst_notes           → per-change justification
      is_known_change         → mark as expected/approved change
                                NOTE: DB CHECK requires analyst_notes to be non-empty
                                      when is_known_change = true
      matched_rt_tickets      → jsonb: auto-matched RT tickets (read-only, from correlation)
    """
    __tablename__ = "report_changes"
    __table_args__ = {"schema": "fim"}

    id                      = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    report_id               = Column(UUID(as_uuid=True), ForeignKey("fim.reports.id"))
    correlation_group_id    = Column(UUID(as_uuid=True))
    alert_id                = Column(UUID(as_uuid=True), ForeignKey("fim.alerts.id", ondelete="CASCADE"))

    agent_hostname          = Column(String(255))
    file_path               = Column(Text)
    change_type             = Column(String(50))
    severity                = Column(String(20))

    # File state
    baseline_hash           = Column(String(64))
    current_hash            = Column(String(64))
    baseline_size           = Column(BigInteger)
    current_size            = Column(BigInteger)
    baseline_mtime          = Column(DateTime)
    current_mtime           = Column(DateTime)

    # RT / ticket linking — use these existing columns
    external_ticket_id      = Column(String(50))        # primary RT# for this change
    linked_rt_tickets       = Column(ARRAY(Text))       # confirmed RT links (text[])
    matched_rt_tickets      = Column(JSONB)             # auto-matched (read-only from correlation)
    rt_ticket_manually_added = Column(Boolean, default=False)

    # Review state — existing columns
    analyst_notes           = Column(Text)              # REQUIRED if is_known_change=True (DB CHECK)
    is_known_change         = Column(Boolean, default=False)
    is_verified             = Column(Boolean, default=False)
    evidence_provided       = Column(Boolean, default=False)
    requires_investigation  = Column(Boolean, default=False)
    skip_lookup             = Column(Boolean, default=False)

    reviewed_at             = Column(DateTime)
    reviewed_by             = Column(UUID(as_uuid=True), ForeignKey("fim.users.id"))
    created_at              = Column(DateTime, server_default=func.now())

    # auditd correlation (optional — see fim.alerts.audit_uid/etc and
    # agent/fim_agent.py's _correlate_auditd). Null unless the source
    # alert had it.
    audit_uid               = Column(String(50))
    audit_process           = Column(Text)
    audit_command           = Column(Text)

    # Relationships
    report                  = relationship("DailyReport", back_populates="changes")


class ReportAgent(Base):
    """Per-agent workflow state — new table from migration 002."""
    __tablename__ = "report_agents"
    __table_args__ = {"schema": "fim"}

    id                  = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    report_id           = Column(UUID(as_uuid=True), ForeignKey("fim.reports.id"), nullable=False)
    agent_hostname      = Column(Text, nullable=False)
    ip_address          = Column(Text)

    # Auto-correlation results
    correlated_rt       = Column(Text)      # best RT ticket number found automatically
    correlated_cmr      = Column(Text)      # best CMR number found automatically

    # Analyst overrides
    manual_rt           = Column(Text)
    correlation_note    = Column(Text)

    # Workflow state: pending / correlated / submitted / skipped
    status              = Column(Text, nullable=False, default="pending")
    is_skipped          = Column(Boolean, default=False)
    skip_reason         = Column(Text)

    correlated_at       = Column(DateTime(timezone=True))
    submitted_at        = Column(DateTime(timezone=True))
    created_at          = Column(DateTime(timezone=True), server_default=func.now())
    updated_at          = Column(DateTime(timezone=True), onupdate=func.now())

    # Relationships
    report              = relationship("DailyReport", back_populates="report_agents")


class ReportTicket(Base):
    """
    Maps to fim.report_tickets — pre-existing table.
    Used for per-report/agent ticket linking.
    source: 'rt' | 'cmr'
    external_id: ticket number
    is_linked: True once analyst confirms
    """
    __tablename__ = "report_tickets"
    __table_args__ = {"schema": "fim"}

    id              = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    report_id       = Column(UUID(as_uuid=True), ForeignKey("fim.reports.id"))
    agent_hostname  = Column(Text, nullable=False)
    source          = Column(String(20))        # 'rt' | 'cmr'
    external_id     = Column(Text, nullable=False)
    summary         = Column(Text)
    url             = Column(Text)
    linked_at       = Column(DateTime, server_default=func.now())
    linked_by       = Column(UUID(as_uuid=True), ForeignKey("fim.users.id"))
    is_linked       = Column(Boolean, default=False)

    # Relationships
    report          = relationship("DailyReport", back_populates="tickets")


class RTTicketCache(Base):
    """
    Maps to fim.rt_ticket_cache — global RT ticket cache with TTL.
    Keyed by ticket_id (unique). keywords[] used for full-text search.
    """
    __tablename__ = "rt_ticket_cache"
    __table_args__ = {"schema": "fim"}

    id           = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    ticket_id    = Column(String(50), unique=True, nullable=False)
    subject      = Column(Text)
    status       = Column(String(50))
    queue        = Column(String(100))
    created      = Column(DateTime)
    last_updated = Column(DateTime)
    keywords     = Column(ARRAY(Text))      # used for hostname search
    ticket_data  = Column(JSONB)
    cached_at    = Column(DateTime, server_default=func.now())
    expires_at   = Column(DateTime)
