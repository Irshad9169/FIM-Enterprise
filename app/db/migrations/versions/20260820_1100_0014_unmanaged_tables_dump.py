"""unmanaged tables: the last 9 with no prior DDL anywhere in this repo

Closes the gap 0000_initial_schema left open. These 9 tables (of the 11 in
env.py's UNMANAGED_TABLES) had no CREATE TABLE anywhere in this repo's
history at all -- not even in a gapNN_*.sh script -- unlike
correlation_groups/anomaly_scores, which 0000_initial_schema already
covered from DDL that did exist in-repo. Guessing these would have risked
silently diverging from the real schema, so this is a verbatim
schema-only pg_dump from the live fim_db on test06 (2026-08-20):

    pg_dump -d fim_db --schema-only --no-owner --no-privileges \
        -t fim.sessions -t fim.agent_health_events -t fim.whitelist_matches \
        -t fim.file_changes -t fim.baseline_history -t fim.retention_policies \
        -t fim.api_keys -t fim.integration_settings -t fim.scans_archive

Reproduced unchanged (dump preamble/session SET statements stripped, not
needed inside a migration). Two things worth knowing since they'd look like
mistakes otherwise: `fim.scans_archive` genuinely has no primary key or any
index in production -- not added here. `fim.file_changes.scan_id` has no FK
to `fim.scans` despite the name -- also not added, faithfully matching
what's actually live.

These 9 remain in env.py's UNMANAGED_TABLES after this migration -- they
still have no SQLAlchemy model, so autogenerate still needs to leave them
alone; this migration only supplies the DDL, not ORM models.

Revision ID: 0014_unmanaged_tables_dump
Revises: 0013_audit_log_immutability
Create Date: 2026-08-20 11:00:00.000000

"""
from typing import Sequence, Union

from alembic import op


revision: str = '0014_unmanaged_tables_dump'
down_revision: Union[str, None] = '0013_audit_log_immutability'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


TABLE_DDL = [
"""
CREATE TABLE fim.agent_health_events (
    id uuid DEFAULT gen_random_uuid() NOT NULL,
    agent_id uuid NOT NULL,
    event_type character varying(50) NOT NULL,
    previous_status character varying(20),
    new_status character varying(20),
    details jsonb,
    created_at timestamp without time zone DEFAULT now()
);
""",
"""
CREATE TABLE fim.api_keys (
    id uuid DEFAULT gen_random_uuid() NOT NULL,
    user_id uuid NOT NULL,
    key character varying(255) NOT NULL,
    name character varying(255) NOT NULL,
    created_at timestamp without time zone DEFAULT CURRENT_TIMESTAMP,
    expires_at timestamp without time zone,
    last_used_at timestamp without time zone,
    is_active boolean DEFAULT true
);
""",
"""
CREATE TABLE fim.baseline_history (
    id uuid DEFAULT gen_random_uuid() NOT NULL,
    baseline_id uuid NOT NULL,
    action character varying(50) NOT NULL,
    performed_by uuid,
    performed_at timestamp without time zone DEFAULT now(),
    details jsonb
);
""",
"""
CREATE TABLE fim.file_changes (
    id uuid DEFAULT gen_random_uuid() NOT NULL,
    scan_id uuid NOT NULL,
    agent_id uuid NOT NULL,
    file_path character varying(1000) NOT NULL,
    change_type character varying(50) NOT NULL,
    old_hash character varying(64),
    new_hash character varying(64),
    old_permissions character varying(10),
    new_permissions character varying(10),
    old_owner integer,
    new_owner integer,
    old_size bigint,
    new_size bigint,
    detected_at timestamp without time zone DEFAULT now(),
    severity character varying(20) DEFAULT 'medium'::character varying,
    is_acknowledged boolean DEFAULT false,
    acknowledged_by uuid,
    acknowledged_at timestamp without time zone,
    notes text
);
""",
"""
CREATE TABLE fim.integration_settings (
    id uuid DEFAULT gen_random_uuid() NOT NULL,
    service_name character varying(50) NOT NULL,
    enabled boolean DEFAULT false,
    base_url text,
    api_key text,
    client_id text,
    client_secret text,
    config jsonb DEFAULT '{}'::jsonb,
    updated_at timestamp without time zone DEFAULT now()
);
""",
"""
CREATE TABLE fim.retention_policies (
    id uuid DEFAULT gen_random_uuid() NOT NULL,
    table_name character varying(100) NOT NULL,
    column_name character varying(100) NOT NULL,
    retain_months integer NOT NULL,
    action character varying(50) NOT NULL,
    is_active boolean DEFAULT false,
    notes text,
    created_at timestamp with time zone DEFAULT now(),
    CONSTRAINT retention_policies_action_check CHECK (((action)::text = ANY ((ARRAY['delete'::character varying, 'null_column'::character varying, 'archive'::character varying])::text[])))
);
""",
"""
CREATE TABLE fim.scans_archive (
    id uuid,
    agent_id uuid,
    scan_type character varying(50),
    status character varying(20),
    files_scanned integer,
    files_changed integer,
    scan_duration integer,
    scan_data jsonb,
    started_at timestamp with time zone,
    completed_at timestamp with time zone,
    created_at timestamp with time zone
);
""",
"""
CREATE TABLE fim.sessions (
    id uuid DEFAULT gen_random_uuid() NOT NULL,
    user_id uuid NOT NULL,
    token_jti character varying(64) NOT NULL,
    ip_address character varying(50),
    user_agent text,
    created_at timestamp without time zone DEFAULT now(),
    expires_at timestamp without time zone NOT NULL,
    last_activity timestamp without time zone DEFAULT now(),
    is_revoked boolean DEFAULT false,
    revoked_at timestamp without time zone,
    revoked_by uuid,
    revoke_reason character varying(50)
);
""",
"""
CREATE TABLE fim.whitelist_matches (
    id uuid DEFAULT gen_random_uuid() NOT NULL,
    rule_id uuid NOT NULL,
    file_path text NOT NULL,
    matched_at timestamp without time zone DEFAULT now(),
    scan_id uuid,
    suppressed_alert boolean DEFAULT true,
    details jsonb
);
""",
]

CONSTRAINT_DDL = [
    "ALTER TABLE ONLY fim.agent_health_events ADD CONSTRAINT agent_health_events_pkey PRIMARY KEY (id);",
    "ALTER TABLE ONLY fim.api_keys ADD CONSTRAINT api_keys_key_key UNIQUE (key);",
    "ALTER TABLE ONLY fim.api_keys ADD CONSTRAINT api_keys_pkey PRIMARY KEY (id);",
    "ALTER TABLE ONLY fim.baseline_history ADD CONSTRAINT baseline_history_pkey PRIMARY KEY (id);",
    "ALTER TABLE ONLY fim.file_changes ADD CONSTRAINT file_changes_pkey PRIMARY KEY (id);",
    "ALTER TABLE ONLY fim.integration_settings ADD CONSTRAINT integration_settings_pkey PRIMARY KEY (id);",
    "ALTER TABLE ONLY fim.integration_settings ADD CONSTRAINT integration_settings_service_name_key UNIQUE (service_name);",
    "ALTER TABLE ONLY fim.retention_policies ADD CONSTRAINT retention_policies_pkey PRIMARY KEY (id);",
    "ALTER TABLE ONLY fim.sessions ADD CONSTRAINT sessions_pkey PRIMARY KEY (id);",
    "ALTER TABLE ONLY fim.sessions ADD CONSTRAINT sessions_token_jti_key UNIQUE (token_jti);",
    "ALTER TABLE ONLY fim.whitelist_matches ADD CONSTRAINT whitelist_matches_pkey PRIMARY KEY (id);",
]

INDEX_DDL = [
    "CREATE INDEX idx_agent_health_events_agent ON fim.agent_health_events USING btree (agent_id, created_at DESC);",
    "CREATE INDEX idx_agent_health_events_type ON fim.agent_health_events USING btree (event_type);",
    "CREATE INDEX idx_api_keys_key ON fim.api_keys USING btree (key);",
    "CREATE INDEX idx_api_keys_user_id ON fim.api_keys USING btree (user_id);",
    "CREATE INDEX idx_file_changes_agent ON fim.file_changes USING btree (agent_id);",
    "CREATE INDEX idx_file_changes_detected ON fim.file_changes USING btree (detected_at DESC);",
    "CREATE INDEX idx_file_changes_scan ON fim.file_changes USING btree (scan_id);",
    "CREATE INDEX idx_file_changes_unacked ON fim.file_changes USING btree (is_acknowledged) WHERE (is_acknowledged = false);",
    "CREATE INDEX idx_sessions_jti ON fim.sessions USING btree (token_jti);",
    "CREATE INDEX idx_sessions_user_id ON fim.sessions USING btree (user_id);",
    "CREATE INDEX idx_sessions_user_revoked ON fim.sessions USING btree (user_id, is_revoked);",
    "CREATE INDEX idx_whitelist_matches_rule ON fim.whitelist_matches USING btree (rule_id, matched_at DESC);",
]

FK_DDL = [
    "ALTER TABLE ONLY fim.agent_health_events ADD CONSTRAINT agent_health_events_agent_id_fkey FOREIGN KEY (agent_id) REFERENCES fim.agents(id) ON DELETE CASCADE;",
    "ALTER TABLE ONLY fim.api_keys ADD CONSTRAINT api_keys_user_id_fkey FOREIGN KEY (user_id) REFERENCES fim.users(id) ON DELETE CASCADE;",
    "ALTER TABLE ONLY fim.baseline_history ADD CONSTRAINT baseline_history_baseline_id_fkey FOREIGN KEY (baseline_id) REFERENCES fim.baselines(id);",
    "ALTER TABLE ONLY fim.baseline_history ADD CONSTRAINT baseline_history_performed_by_fkey FOREIGN KEY (performed_by) REFERENCES fim.users(id);",
    "ALTER TABLE ONLY fim.file_changes ADD CONSTRAINT file_changes_acknowledged_by_fkey FOREIGN KEY (acknowledged_by) REFERENCES fim.users(id);",
    "ALTER TABLE ONLY fim.file_changes ADD CONSTRAINT file_changes_agent_id_fkey FOREIGN KEY (agent_id) REFERENCES fim.agents(id);",
    "ALTER TABLE ONLY fim.sessions ADD CONSTRAINT sessions_revoked_by_fkey FOREIGN KEY (revoked_by) REFERENCES fim.users(id);",
    "ALTER TABLE ONLY fim.sessions ADD CONSTRAINT sessions_user_id_fkey FOREIGN KEY (user_id) REFERENCES fim.users(id) ON DELETE CASCADE;",
    "ALTER TABLE ONLY fim.whitelist_matches ADD CONSTRAINT whitelist_matches_rule_id_fkey FOREIGN KEY (rule_id) REFERENCES fim.whitelist_rules(id) ON DELETE CASCADE;",
]


def upgrade() -> None:
    for ddl in TABLE_DDL:
        op.execute(ddl)
    for ddl in CONSTRAINT_DDL:
        op.execute(ddl)
    for ddl in INDEX_DDL:
        op.execute(ddl)
    for ddl in FK_DDL:
        op.execute(ddl)


def downgrade() -> None:
    op.execute("""
        DROP TABLE IF EXISTS
            fim.agent_health_events, fim.api_keys, fim.baseline_history,
            fim.file_changes, fim.integration_settings, fim.retention_policies,
            fim.scans_archive, fim.sessions, fim.whitelist_matches
        CASCADE;
    """)
