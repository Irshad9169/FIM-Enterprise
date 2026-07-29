"""
Database Models - Complete Comprehensive Version
"""
from sqlalchemy import Column, String, Integer, Boolean, DateTime, Text, BigInteger, UUID, ForeignKey, TIMESTAMP
from sqlalchemy.dialects.postgresql import JSONB, ARRAY
from sqlalchemy.orm import relationship
from datetime import datetime
import uuid

from app.core.database import Base

class User(Base):
    __tablename__ = "users"
    __table_args__ = {"schema": "fim"}
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    username = Column(String(100), unique=True, nullable=False)
    email = Column(String(255), unique=True, nullable=False)
    password_hash = Column(String(255), nullable=False)
    full_name = Column(String(255))
    role = Column(String(50), default="viewer")
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

class Agent(Base):
    __tablename__ = "agents"
    __table_args__ = {"schema": "fim"}
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    hostname = Column(String(255), unique=True, nullable=False)
    ip_address = Column(String(50))
    os_type = Column(String(50))
    os_version = Column(String(100))
    agent_version = Column(String(20))
    status = Column(String(20), default="offline")
    last_heartbeat = Column(DateTime)
    tags = Column(JSONB)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    expected_heartbeat_interval = Column(Integer, default=300)
    heartbeat_timeout = Column(Integer, default=600)
    is_healthy = Column(Boolean, default=True)
    last_heartbeat_alert = Column(DateTime)
    last_scan_at = Column(DateTime)
    scan_count = Column(Integer, default=0)

class Policy(Base):
    __tablename__ = "policies"
    __table_args__ = {"schema": "fim"}
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    name = Column(String(255), unique=True, nullable=False)
    description = Column(Text)
    paths = Column(ARRAY(Text))
    exclude_patterns = Column(ARRAY(Text))
    enabled = Column(Boolean, default=True)
    created_at = Column(DateTime, default=datetime.utcnow)

class Alert(Base):
    __tablename__ = "alerts"
    __table_args__ = {"schema": "fim"}
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    agent_id = Column(UUID(as_uuid=True), ForeignKey("fim.agents.id", ondelete="CASCADE"))
    policy_id = Column(UUID(as_uuid=True), ForeignKey("fim.policies.id"))
    alert_type = Column(String(50), nullable=False)
    severity = Column(String(20), nullable=False)
    file_path = Column(String(1024), nullable=False)
    previous_state = Column(JSONB)
    current_state = Column(JSONB)
    change_details = Column(JSONB)
    status = Column(String(20), default="open")
    assigned_to = Column(UUID(as_uuid=True), ForeignKey("fim.users.id"))
    resolution_notes = Column(Text)
    detected_at = Column(DateTime, default=datetime.utcnow)
    acknowledged_at = Column(DateTime)
    resolved_at = Column(DateTime)
    created_at = Column(DateTime, default=datetime.utcnow)
    is_whitelisted = Column(Boolean, default=False)
    whitelist_rule_id = Column(UUID(as_uuid=True), ForeignKey("fim.whitelist_rules.id"))
    triggered_by_rule = Column(UUID(as_uuid=True), ForeignKey("fim.alert_rules.id"))
    acknowledged_by = Column(UUID(as_uuid=True), ForeignKey("fim.users.id"))
    alert_group_id = Column(UUID(as_uuid=True))
    occurrence_count = Column(Integer, default=1)

class Baseline(Base):
    __tablename__ = "baselines"
    __table_args__ = {"schema": "fim"}
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    agent_id = Column(UUID(as_uuid=True), ForeignKey("fim.agents.id", ondelete="CASCADE"))
    baseline_name = Column(String(255))
    baseline_data = Column(JSONB)
    file_count = Column(Integer)
    total_size_bytes = Column(BigInteger)
    checksum = Column(String(64))
    created_at = Column(DateTime, default=datetime.utcnow)
    is_active = Column(Boolean, default=True)
    status = Column(String(20), default='pending')
    is_approved = Column(Boolean, default=False)
    approved_by = Column(UUID(as_uuid=True), ForeignKey("fim.users.id"))
    approved_at = Column(DateTime)
    created_by = Column(UUID(as_uuid=True), ForeignKey("fim.users.id"))
    notes = Column(Text)
    git_hash = Column(String(40))
    snapshot_path = Column(Text)
    diff_signature = Column(String(64))
    diff_generated_at = Column(TIMESTAMP(timezone=True))
    diff_sig_algorithm = Column(String(20), default='HMAC-SHA256')

class AuditLog(Base):
    __tablename__ = "audit_logs"
    __table_args__ = {"schema": "fim"}
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id = Column(UUID(as_uuid=True), ForeignKey("fim.users.id"))
    username = Column(String(100))
    action = Column(String(100), nullable=False)
    resource_type = Column(String(50))
    resource_id = Column(UUID(as_uuid=True))
    details = Column(JSONB)
    ip_address = Column(String(50))
    user_agent = Column(Text)
    timestamp = Column(DateTime, default=datetime.utcnow)
    entry_hash = Column(String(64))
    prev_hash = Column(String(64), default='0' * 64)

class AlertRule(Base):
    __tablename__ = "alert_rules"
    __table_args__ = {"schema": "fim"}
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    name = Column(String(255), nullable=False)
    description = Column(Text)
    rule_type = Column(String(50), nullable=False)
    conditions = Column(JSONB, nullable=False)
    actions = Column(JSONB, nullable=False)
    severity = Column(String(20), default="medium")
    enabled = Column(Boolean, default=True)
    created_by = Column(UUID(as_uuid=True), ForeignKey("fim.users.id"))
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

class RuleExecution(Base):
    __tablename__ = "rule_executions"
    __table_args__ = {"schema": "fim"}
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    rule_id = Column(UUID(as_uuid=True), ForeignKey("fim.alert_rules.id", ondelete="CASCADE"))
    executed_at = Column(DateTime, default=datetime.utcnow)
    matched = Column(Boolean)
    alert_count = Column(Integer)
    details = Column(JSONB)

class ComplianceFramework(Base):
    __tablename__ = "compliance_frameworks"
    __table_args__ = {"schema": "fim"}
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    name = Column(String(100), unique=True, nullable=False)
    version = Column(String(20))
    description = Column(Text)
    active = Column(Boolean, default=True)
    created_at = Column(DateTime, default=datetime.utcnow)

class ComplianceControl(Base):
    __tablename__ = "compliance_controls"
    __table_args__ = {"schema": "fim"}
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    framework_id = Column(UUID(as_uuid=True), ForeignKey("fim.compliance_frameworks.id", ondelete="CASCADE"))
    control_id = Column(String(50), nullable=False)
    control_name = Column(String(255), nullable=False)
    description = Column(Text)
    category = Column(String(100))
    severity = Column(String(20))
    created_at = Column(DateTime, default=datetime.utcnow)

class PolicyControlMapping(Base):
    __tablename__ = "policy_control_mapping"
    __table_args__ = {"schema": "fim"}
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    policy_name = Column(String(255), nullable=False)
    control_id = Column(UUID(as_uuid=True), ForeignKey("fim.compliance_controls.id", ondelete="CASCADE"))
    coverage_percentage = Column(Integer, default=100)
    notes = Column(Text)
    created_at = Column(DateTime, default=datetime.utcnow)

class ComplianceViolation(Base):
    __tablename__ = "compliance_violations"
    __table_args__ = {"schema": "fim"}
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    alert_id = Column(UUID(as_uuid=True), ForeignKey("fim.alerts.id", ondelete="CASCADE"))
    control_id = Column(UUID(as_uuid=True), ForeignKey("fim.compliance_controls.id", ondelete="CASCADE"))
    violation_type = Column(String(50))
    detected_at = Column(DateTime, default=datetime.utcnow)
    resolved_at = Column(DateTime)
    resolution_notes = Column(Text)
    status = Column(String(20), default="open")

class ComplianceReport(Base):
    __tablename__ = "compliance_reports"
    __table_args__ = {"schema": "fim"}
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    framework_id = Column(UUID(as_uuid=True), ForeignKey("fim.compliance_frameworks.id", ondelete="CASCADE"))
    report_type = Column(String(50))
    period_start = Column(DateTime, nullable=False)
    period_end = Column(DateTime, nullable=False)
    report_data = Column(JSONB)
    generated_by = Column(UUID(as_uuid=True), ForeignKey("fim.users.id"))
    generated_at = Column(DateTime, default=datetime.utcnow)
    file_path = Column(Text)

class Scan(Base):
    __tablename__ = "scans"
    __table_args__ = {"schema": "fim"}
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    agent_id = Column(UUID(as_uuid=True), ForeignKey('fim.agents.id'), nullable=False)
    scan_type = Column(String(50), default="full")
    status = Column(String(50), default="running")
    files_scanned = Column(Integer, default=0)
    files_changed = Column(Integer, default=0)
    scan_duration = Column(Integer, default=0)
    scan_data = Column(JSONB)
    started_at = Column(DateTime, default=datetime.utcnow)
    completed_at = Column(DateTime)
    created_at = Column(DateTime, default=datetime.utcnow)

class WhitelistRule(Base):
    __tablename__ = "whitelist_rules"
    __table_args__ = {"schema": "fim"}
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    rule_name = Column(String(255), unique=True, nullable=False)
    rule_type = Column(String(50), nullable=False)
    match_value = Column(Text, nullable=False)
    reason = Column(Text)
    severity_override = Column(String(20))
    is_active = Column(Boolean, default=True)
    is_temporary = Column(Boolean, default=False)
    expires_at = Column(DateTime)
    created_by = Column(UUID(as_uuid=True), ForeignKey("fim.users.id"))
    created_at = Column(DateTime, default=datetime.utcnow)
    last_matched_at = Column(DateTime)
    match_count = Column(Integer, default=0)
    scope = Column(String(20), default='global')
    agent_id = Column(UUID(as_uuid=True), ForeignKey("fim.agents.id", ondelete="CASCADE"))

class ScanRequest(Base):
    __tablename__ = "scan_requests"
    __table_args__ = {"schema": "fim"}
    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    agent_id = Column(UUID(as_uuid=True), ForeignKey("fim.agents.id", ondelete="CASCADE"))
    requested_by = Column(UUID(as_uuid=True), ForeignKey("fim.users.id"))
    status = Column(String(20), default="pending")
    requested_at = Column(DateTime, default=datetime.utcnow)
    acknowledged_at = Column(DateTime)
    completed_at = Column(DateTime)
    timeout_at = Column(DateTime)
    error_message = Column(Text)
    scan_id = Column(UUID(as_uuid=True), ForeignKey("fim.scans.id", ondelete="SET NULL"))
    started_at = Column(DateTime)
