"""initial schema: create the fim schema and its tables from nothing

Until this migration, running `alembic upgrade head` against a genuinely
empty Postgres database created almost nothing — 0001 is a no-op "reconcile"
marker, and the only real `create_table` anywhere in the chain (0002-0012)
was `system_settings`. Every other table was assumed to already exist,
because on every real deployment so far it always did (created by hand or
by early gapNN_*.sh scripts, years before Alembic was adopted). That made a
true from-scratch install impossible without `pg_dump`/`pg_restore` from an
existing instance — see docs/PRODUCTION_DEPLOYMENT.md section 4.

This migration creates the `fim` schema plus the 24 tables we can build
with full confidence, from two kinds of verified source:

  - The 22 tables SQLAlchemy already models (app/models/models.py,
    app/models/daily_report.py) — DDL below was generated mechanically via
    `CreateTable(table).compile(dialect=postgresql.dialect())` against the
    real ORM metadata, not hand-transcribed, so it's exactly what the
    models actually declare.
  - `correlation_groups` and `anomaly_scores` — two of the eleven
    "unmanaged" raw-SQL tables (see UNMANAGED_TABLES in env.py), whose
    CREATE TABLE statements already exist verbatim in-repo
    (database/migrations/001_phase1_schema.sql and
    scripts/gap19_anomaly_detection.sh) and are reproduced here unchanged.

Deliberately NOT at their current, full column set: `alerts`, `report_changes`,
and `agents` below only have the columns that predate 0002 — everything 0002-0010
add via `op.add_column` (alerts.entry_hash/prev_hash/audit_uid/audit_process/
audit_command, report_changes.audit_uid/audit_process/audit_command/content_diff,
agents.binary_hash/binary_hash_mismatch_since/pending_binary_hash/desired_config/
desired_config_version/applied_config_version/reported_config/api_key_hash/
scan_pause_requested/scan_status/scan_progress_total/scan_progress_processed/
scan_progress_updated_at) is intentionally omitted here so those migrations can
add them on top without hitting "column already exists". Likewise
`system_settings` is omitted entirely — 0012 creates it outright. This mirrors
exactly what already happened historically on every real deployment: base table,
then incremental ALTERs layered on by the later migrations.

NOT included — nine more UNMANAGED_TABLES have no CREATE TABLE anywhere in
this repo's history at all (sessions, agent_health_events,
whitelist_matches, file_changes, baseline_history, retention_policies,
api_keys, integration_settings, scans_archive). Guessing their DDL from
application code that reads/writes them would risk silently diverging from
the real production schema — exactly the kind of drift this migration
exists to stop. A fresh install today is missing only these nine; pull
their real DDL with:

    pg_dump -d fim_db --schema-only --no-owner --no-privileges \
        -t fim.sessions -t fim.agent_health_events -t fim.whitelist_matches \
        -t fim.file_changes -t fim.baseline_history -t fim.retention_policies \
        -t fim.api_keys -t fim.integration_settings -t fim.scans_archive \
        > nine_unmanaged_tables.sql

against an existing instance, then fold the result into a follow-up
migration (append to UNMANAGED_TABLES-minus-whatever-you-added in env.py
once done, same as any newly-modeled table).

Revision ID: 0000_initial_schema
Revises:
Create Date: 2026-08-20 10:00:00.000000

"""
from typing import Sequence, Union

from alembic import op


revision: str = '0000_initial_schema'
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


# The 22 ORM-modeled tables, in FK-dependency order (Base.metadata.sorted_tables) —
# generated via CreateTable(table).compile(dialect=postgresql.dialect()), not typed by hand.
ORM_TABLE_DDL = [
"""
CREATE TABLE fim.agents (
	id UUID NOT NULL,
	hostname VARCHAR(255) NOT NULL,
	ip_address VARCHAR(50),
	os_type VARCHAR(50),
	os_version VARCHAR(100),
	agent_version VARCHAR(20),
	status VARCHAR(20),
	last_heartbeat TIMESTAMP WITHOUT TIME ZONE,
	tags JSONB,
	created_at TIMESTAMP WITHOUT TIME ZONE,
	updated_at TIMESTAMP WITHOUT TIME ZONE,
	expected_heartbeat_interval INTEGER,
	heartbeat_timeout INTEGER,
	is_healthy BOOLEAN,
	last_heartbeat_alert TIMESTAMP WITHOUT TIME ZONE,
	last_scan_at TIMESTAMP WITHOUT TIME ZONE,
	scan_count INTEGER,
	PRIMARY KEY (id),
	UNIQUE (hostname)
);
""",
"""
CREATE TABLE fim.compliance_frameworks (
	id UUID NOT NULL,
	name VARCHAR(100) NOT NULL,
	version VARCHAR(20),
	description TEXT,
	active BOOLEAN,
	created_at TIMESTAMP WITHOUT TIME ZONE,
	PRIMARY KEY (id),
	UNIQUE (name)
);
""",
"""
CREATE TABLE fim.policies (
	id UUID NOT NULL,
	name VARCHAR(255) NOT NULL,
	description TEXT,
	paths TEXT[],
	exclude_patterns TEXT[],
	enabled BOOLEAN,
	created_at TIMESTAMP WITHOUT TIME ZONE,
	PRIMARY KEY (id),
	UNIQUE (name)
);
""",
"""
CREATE TABLE fim.rt_ticket_cache (
	id UUID NOT NULL,
	ticket_id VARCHAR(50) NOT NULL,
	subject TEXT,
	status VARCHAR(50),
	queue VARCHAR(100),
	created TIMESTAMP WITHOUT TIME ZONE,
	last_updated TIMESTAMP WITHOUT TIME ZONE,
	keywords TEXT[],
	ticket_data JSONB,
	cached_at TIMESTAMP WITHOUT TIME ZONE DEFAULT now(),
	expires_at TIMESTAMP WITHOUT TIME ZONE,
	PRIMARY KEY (id),
	UNIQUE (ticket_id)
);
""",
"""
CREATE TABLE fim.users (
	id UUID NOT NULL,
	username VARCHAR(100) NOT NULL,
	email VARCHAR(255) NOT NULL,
	password_hash VARCHAR(255) NOT NULL,
	full_name VARCHAR(255),
	role VARCHAR(50),
	is_active BOOLEAN,
	created_at TIMESTAMP WITHOUT TIME ZONE,
	updated_at TIMESTAMP WITHOUT TIME ZONE,
	last_login TIMESTAMP WITHOUT TIME ZONE,
	last_login_ip VARCHAR(50),
	mfa_enabled BOOLEAN,
	mfa_secret TEXT,
	mfa_confirmed BOOLEAN,
	PRIMARY KEY (id),
	UNIQUE (username),
	UNIQUE (email)
);
""",
"""
CREATE TABLE fim.alert_rules (
	id UUID NOT NULL,
	name VARCHAR(255) NOT NULL,
	description TEXT,
	rule_type VARCHAR(50) NOT NULL,
	conditions JSONB NOT NULL,
	actions JSONB NOT NULL,
	severity VARCHAR(20),
	enabled BOOLEAN,
	created_by UUID,
	created_at TIMESTAMP WITHOUT TIME ZONE,
	updated_at TIMESTAMP WITHOUT TIME ZONE,
	PRIMARY KEY (id),
	FOREIGN KEY(created_by) REFERENCES fim.users (id)
);
""",
"""
CREATE TABLE fim.audit_logs (
	id UUID NOT NULL,
	user_id UUID,
	username VARCHAR(100),
	action VARCHAR(100) NOT NULL,
	resource_type VARCHAR(50),
	resource_id UUID,
	details JSONB,
	ip_address VARCHAR(50),
	user_agent TEXT,
	timestamp TIMESTAMP WITHOUT TIME ZONE,
	entry_hash VARCHAR(64),
	prev_hash VARCHAR(64),
	PRIMARY KEY (id),
	FOREIGN KEY(user_id) REFERENCES fim.users (id)
);
""",
"""
CREATE TABLE fim.baselines (
	id UUID NOT NULL,
	agent_id UUID,
	baseline_name VARCHAR(255),
	baseline_data JSONB,
	file_count INTEGER,
	total_size_bytes BIGINT,
	checksum VARCHAR(64),
	created_at TIMESTAMP WITHOUT TIME ZONE,
	is_active BOOLEAN,
	status VARCHAR(20),
	is_approved BOOLEAN,
	approved_by UUID,
	approved_at TIMESTAMP WITHOUT TIME ZONE,
	created_by UUID,
	notes TEXT,
	git_hash VARCHAR(40),
	snapshot_path TEXT,
	diff_signature VARCHAR(64),
	diff_generated_at TIMESTAMP WITH TIME ZONE,
	diff_sig_algorithm VARCHAR(20),
	PRIMARY KEY (id),
	FOREIGN KEY(agent_id) REFERENCES fim.agents (id) ON DELETE CASCADE,
	FOREIGN KEY(approved_by) REFERENCES fim.users (id),
	FOREIGN KEY(created_by) REFERENCES fim.users (id)
);
""",
"""
CREATE TABLE fim.compliance_controls (
	id UUID NOT NULL,
	framework_id UUID,
	control_id VARCHAR(50) NOT NULL,
	control_name VARCHAR(255) NOT NULL,
	description TEXT,
	category VARCHAR(100),
	severity VARCHAR(20),
	created_at TIMESTAMP WITHOUT TIME ZONE,
	PRIMARY KEY (id),
	FOREIGN KEY(framework_id) REFERENCES fim.compliance_frameworks (id) ON DELETE CASCADE
);
""",
"""
CREATE TABLE fim.compliance_reports (
	id UUID NOT NULL,
	framework_id UUID,
	report_type VARCHAR(50),
	period_start TIMESTAMP WITHOUT TIME ZONE NOT NULL,
	period_end TIMESTAMP WITHOUT TIME ZONE NOT NULL,
	report_data JSONB,
	generated_by UUID,
	generated_at TIMESTAMP WITHOUT TIME ZONE,
	file_path TEXT,
	PRIMARY KEY (id),
	FOREIGN KEY(framework_id) REFERENCES fim.compliance_frameworks (id) ON DELETE CASCADE,
	FOREIGN KEY(generated_by) REFERENCES fim.users (id)
);
""",
"""
CREATE TABLE fim.reports (
	id UUID NOT NULL,
	report_type VARCHAR(20),
	report_date DATE,
	date_from DATE,
	date_to DATE,
	total_changes INTEGER,
	total_servers INTEGER,
	known_changes INTEGER,
	unknown_changes INTEGER,
	correlation_groups_count INTEGER,
	total_added INTEGER,
	total_removed INTEGER,
	total_changed INTEGER,
	status VARCHAR(20),
	agent_list TEXT[],
	submitted_agents TEXT[],
	agents_total INTEGER,
	analyst_notes TEXT,
	rt_ticket_searched BOOLEAN,
	rt_ticket_found BOOLEAN,
	rt_ticket_id VARCHAR(50),
	rt_ticket_url TEXT,
	rt_search_error TEXT,
	generated_by UUID,
	reviewed_by UUID,
	submitted_by UUID,
	submitted_at TIMESTAMP WITHOUT TIME ZONE,
	created_at TIMESTAMP WITHOUT TIME ZONE DEFAULT now(),
	updated_at TIMESTAMP WITHOUT TIME ZONE DEFAULT now(),
	correlation_run_at TIMESTAMP WITH TIME ZONE,
	published_at TIMESTAMP WITH TIME ZONE,
	published_by UUID,
	PRIMARY KEY (id),
	FOREIGN KEY(generated_by) REFERENCES fim.users (id),
	FOREIGN KEY(reviewed_by) REFERENCES fim.users (id),
	FOREIGN KEY(submitted_by) REFERENCES fim.users (id)
);
""",
"""
CREATE TABLE fim.scans (
	id UUID NOT NULL,
	agent_id UUID NOT NULL,
	scan_type VARCHAR(50),
	status VARCHAR(20),
	files_scanned INTEGER,
	files_changed INTEGER,
	scan_duration INTEGER,
	scan_data JSONB,
	started_at TIMESTAMP WITH TIME ZONE,
	completed_at TIMESTAMP WITH TIME ZONE,
	created_at TIMESTAMP WITH TIME ZONE,
	PRIMARY KEY (id),
	FOREIGN KEY(agent_id) REFERENCES fim.agents (id)
);
""",
"""
CREATE TABLE fim.whitelist_rules (
	id UUID NOT NULL,
	rule_name VARCHAR(255) NOT NULL,
	rule_type VARCHAR(50) NOT NULL,
	match_value TEXT NOT NULL,
	reason TEXT,
	severity_override VARCHAR(20),
	is_active BOOLEAN,
	is_temporary BOOLEAN,
	expires_at TIMESTAMP WITHOUT TIME ZONE,
	created_by UUID,
	created_at TIMESTAMP WITHOUT TIME ZONE,
	last_matched_at TIMESTAMP WITHOUT TIME ZONE,
	match_count INTEGER,
	scope VARCHAR(20),
	agent_id UUID,
	status VARCHAR(20),
	approved_by UUID,
	approved_at TIMESTAMP WITH TIME ZONE,
	rejection_reason TEXT,
	PRIMARY KEY (id),
	UNIQUE (rule_name),
	FOREIGN KEY(created_by) REFERENCES fim.users (id),
	FOREIGN KEY(agent_id) REFERENCES fim.agents (id) ON DELETE CASCADE,
	FOREIGN KEY(approved_by) REFERENCES fim.users (id) ON DELETE SET NULL
);
""",
"""
CREATE TABLE fim.alerts (
	id UUID NOT NULL,
	agent_id UUID,
	policy_id UUID,
	alert_type VARCHAR(50) NOT NULL,
	severity VARCHAR(20) NOT NULL,
	file_path VARCHAR(1024) NOT NULL,
	previous_state JSONB,
	current_state JSONB,
	change_details JSONB,
	status VARCHAR(20),
	assigned_to UUID,
	resolution_notes TEXT,
	detected_at TIMESTAMP WITHOUT TIME ZONE,
	acknowledged_at TIMESTAMP WITHOUT TIME ZONE,
	resolved_at TIMESTAMP WITHOUT TIME ZONE,
	created_at TIMESTAMP WITHOUT TIME ZONE,
	is_whitelisted BOOLEAN,
	whitelist_rule_id UUID,
	triggered_by_rule UUID,
	acknowledged_by UUID,
	alert_group_id UUID,
	occurrence_count INTEGER,
	PRIMARY KEY (id),
	FOREIGN KEY(agent_id) REFERENCES fim.agents (id) ON DELETE CASCADE,
	FOREIGN KEY(policy_id) REFERENCES fim.policies (id),
	FOREIGN KEY(assigned_to) REFERENCES fim.users (id),
	FOREIGN KEY(whitelist_rule_id) REFERENCES fim.whitelist_rules (id),
	FOREIGN KEY(triggered_by_rule) REFERENCES fim.alert_rules (id),
	FOREIGN KEY(acknowledged_by) REFERENCES fim.users (id)
);
""",
"""
CREATE TABLE fim.policy_control_mapping (
	id UUID NOT NULL,
	policy_name VARCHAR(255) NOT NULL,
	control_id UUID,
	coverage_percentage INTEGER,
	notes TEXT,
	created_at TIMESTAMP WITHOUT TIME ZONE,
	PRIMARY KEY (id),
	FOREIGN KEY(control_id) REFERENCES fim.compliance_controls (id) ON DELETE CASCADE
);
""",
"""
CREATE TABLE fim.report_agents (
	id UUID NOT NULL,
	report_id UUID NOT NULL,
	agent_hostname TEXT NOT NULL,
	ip_address TEXT,
	correlated_rt TEXT,
	correlated_cmr TEXT,
	manual_rt TEXT,
	correlation_note TEXT,
	status TEXT NOT NULL,
	is_skipped BOOLEAN,
	skip_reason TEXT,
	correlated_at TIMESTAMP WITH TIME ZONE,
	submitted_at TIMESTAMP WITH TIME ZONE,
	created_at TIMESTAMP WITH TIME ZONE DEFAULT now(),
	updated_at TIMESTAMP WITH TIME ZONE,
	PRIMARY KEY (id),
	FOREIGN KEY(report_id) REFERENCES fim.reports (id)
);
""",
"""
CREATE TABLE fim.report_tickets (
	id UUID NOT NULL,
	report_id UUID,
	agent_hostname TEXT NOT NULL,
	source VARCHAR(20),
	external_id TEXT NOT NULL,
	summary TEXT,
	url TEXT,
	linked_at TIMESTAMP WITHOUT TIME ZONE DEFAULT now(),
	linked_by UUID,
	is_linked BOOLEAN,
	PRIMARY KEY (id),
	FOREIGN KEY(report_id) REFERENCES fim.reports (id),
	FOREIGN KEY(linked_by) REFERENCES fim.users (id)
);
""",
"""
CREATE TABLE fim.rule_executions (
	id UUID NOT NULL,
	rule_id UUID,
	executed_at TIMESTAMP WITHOUT TIME ZONE,
	matched BOOLEAN,
	alert_count INTEGER,
	details JSONB,
	PRIMARY KEY (id),
	FOREIGN KEY(rule_id) REFERENCES fim.alert_rules (id) ON DELETE CASCADE
);
""",
"""
CREATE TABLE fim.scan_requests (
	id UUID NOT NULL,
	agent_id UUID,
	requested_by UUID,
	status VARCHAR(20),
	requested_at TIMESTAMP WITHOUT TIME ZONE,
	acknowledged_at TIMESTAMP WITHOUT TIME ZONE,
	completed_at TIMESTAMP WITHOUT TIME ZONE,
	timeout_at TIMESTAMP WITHOUT TIME ZONE,
	error_message TEXT,
	scan_id UUID,
	priority VARCHAR(20),
	started_at TIMESTAMP WITHOUT TIME ZONE,
	PRIMARY KEY (id),
	FOREIGN KEY(agent_id) REFERENCES fim.agents (id) ON DELETE CASCADE,
	FOREIGN KEY(requested_by) REFERENCES fim.users (id),
	FOREIGN KEY(scan_id) REFERENCES fim.scans (id) ON DELETE SET NULL
);
""",
"""
CREATE TABLE fim.compliance_violations (
	id UUID NOT NULL,
	alert_id UUID,
	control_id UUID,
	violation_type VARCHAR(50),
	detected_at TIMESTAMP WITHOUT TIME ZONE,
	resolved_at TIMESTAMP WITHOUT TIME ZONE,
	resolution_notes TEXT,
	status VARCHAR(20),
	PRIMARY KEY (id),
	FOREIGN KEY(alert_id) REFERENCES fim.alerts (id) ON DELETE CASCADE,
	FOREIGN KEY(control_id) REFERENCES fim.compliance_controls (id) ON DELETE CASCADE
);
""",
"""
CREATE TABLE fim.report_changes (
	id UUID NOT NULL,
	report_id UUID,
	correlation_group_id UUID,
	alert_id UUID,
	agent_hostname VARCHAR(255),
	file_path TEXT,
	change_type VARCHAR(50),
	severity VARCHAR(20),
	baseline_hash VARCHAR(64),
	current_hash VARCHAR(64),
	baseline_size BIGINT,
	current_size BIGINT,
	baseline_mtime TIMESTAMP WITHOUT TIME ZONE,
	current_mtime TIMESTAMP WITHOUT TIME ZONE,
	external_ticket_id VARCHAR(50),
	linked_rt_tickets TEXT[],
	matched_rt_tickets JSONB,
	rt_ticket_manually_added BOOLEAN,
	analyst_notes TEXT,
	is_known_change BOOLEAN,
	is_verified BOOLEAN,
	evidence_provided BOOLEAN,
	requires_investigation BOOLEAN,
	skip_lookup BOOLEAN,
	reviewed_at TIMESTAMP WITHOUT TIME ZONE,
	reviewed_by UUID,
	created_at TIMESTAMP WITHOUT TIME ZONE DEFAULT now(),
	PRIMARY KEY (id),
	FOREIGN KEY(report_id) REFERENCES fim.reports (id),
	FOREIGN KEY(alert_id) REFERENCES fim.alerts (id) ON DELETE CASCADE,
	FOREIGN KEY(reviewed_by) REFERENCES fim.users (id)
);
""",
]

# Two of the eleven UNMANAGED_TABLES (env.py) whose real DDL already exists
# verbatim elsewhere in-repo. Appended after the ORM tables since both only
# depend on tables created above (reports/users, agents).
UNMANAGED_TABLE_DDL = [
    # database/migrations/001_phase1_schema.sql, unchanged.
    """
CREATE TABLE fim.correlation_groups (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    report_id UUID REFERENCES fim.reports(id) ON DELETE CASCADE,
    group_name VARCHAR(255) NOT NULL,
    group_label VARCHAR(255) NOT NULL,
    file_pattern VARCHAR(255),
    change_type VARCHAR(50),
    package_name VARCHAR(255),
    server_count INTEGER DEFAULT 0,
    change_count INTEGER DEFAULT 0,
    similarity_score FLOAT DEFAULT 0.0,
    is_known BOOLEAN DEFAULT FALSE,
    reviewed_at TIMESTAMP,
    reviewed_by UUID REFERENCES fim.users(id),
    created_at TIMESTAMP DEFAULT NOW()
);
""",
    "CREATE INDEX idx_correlation_groups_report ON fim.correlation_groups(report_id);",
    "CREATE INDEX idx_correlation_groups_pattern ON fim.correlation_groups(file_pattern);",
    "CREATE INDEX idx_correlation_groups_package ON fim.correlation_groups(package_name);",
    "CREATE INDEX idx_correlation_groups_known ON fim.correlation_groups(is_known);",
    # scripts/gap19_anomaly_detection.sh, unchanged (GRANT omitted — the
    # migration-running role owns what it creates, see PRODUCTION_DEPLOYMENT.md §4).
    """
CREATE TABLE fim.anomaly_scores (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    agent_id        UUID NOT NULL REFERENCES fim.agents(id) ON DELETE CASCADE,
    computed_at     TIMESTAMPTZ DEFAULT NOW(),
    score           INTEGER NOT NULL DEFAULT 0
                        CHECK (score >= 0 AND score <= 100),
    level           VARCHAR(10) NOT NULL DEFAULT 'low'
                        CHECK (level IN ('low','medium','high','critical')),
    alerts_today    INTEGER DEFAULT 0,
    alerts_avg_7d   NUMERIC(8,2) DEFAULT 0,
    z_score         NUMERIC(8,2) DEFAULT 0,
    volume_spike    BOOLEAN DEFAULT FALSE,
    repeated_files  INTEGER DEFAULT 0,
    repeat_details  JSONB DEFAULT '[]',
    summary         TEXT,
    UNIQUE (agent_id, computed_at)
);
""",
    "CREATE INDEX idx_anomaly_agent_computed ON fim.anomaly_scores(agent_id, computed_at DESC);",
    "CREATE INDEX idx_anomaly_level ON fim.anomaly_scores(level, computed_at DESC);",
]


def upgrade() -> None:
    op.execute("CREATE SCHEMA IF NOT EXISTS fim;")
    for ddl in ORM_TABLE_DDL:
        op.execute(ddl)
    for ddl in UNMANAGED_TABLE_DDL:
        op.execute(ddl)


def downgrade() -> None:
    op.execute("DROP SCHEMA fim CASCADE;")
