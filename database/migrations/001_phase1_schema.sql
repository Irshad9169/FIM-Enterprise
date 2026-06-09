-- ============================================================================
-- FIM Phase 1: Foundation Schema Migration
-- ============================================================================

\c fim_db

SET search_path TO fim;

-- ============================================================================
-- 1. Update users table with new roles
-- ============================================================================

-- Drop existing role constraint if exists
ALTER TABLE fim.users DROP CONSTRAINT IF EXISTS users_role_check;

-- Add new constraint with all roles
ALTER TABLE fim.users 
  ADD CONSTRAINT users_role_check 
  CHECK (role IN ('admin', 'analyst', 'trainee', 'auditor', 'viewer'));

COMMENT ON COLUMN fim.users.role IS 'User role: admin (full access), analyst (generate/review/submit), trainee (review/submit), auditor (read-only), viewer (deprecated)';

-- ============================================================================
-- 2. Reports table
-- ============================================================================

CREATE TABLE IF NOT EXISTS fim.reports (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    report_type VARCHAR(20) DEFAULT 'daily' CHECK (report_type IN ('daily', 'custom')),
    report_date DATE, -- For daily reports
    date_from DATE,   -- For custom range reports
    date_to DATE,     -- For custom range reports
    
    -- Statistics
    total_changes INTEGER DEFAULT 0,
    total_servers INTEGER DEFAULT 0,
    known_changes INTEGER DEFAULT 0,
    unknown_changes INTEGER DEFAULT 0,
    correlation_groups_count INTEGER DEFAULT 0,
    
    -- Workflow
    status VARCHAR(20) DEFAULT 'pending' CHECK (status IN ('pending', 'in_review', 'reviewed', 'submitted', 'submitted_no_ticket')),
    
    -- Ownership
    generated_by UUID REFERENCES fim.users(id),
    reviewed_by UUID REFERENCES fim.users(id),
    submitted_by UUID REFERENCES fim.users(id),
    
    -- RT Integration
    rt_ticket_searched BOOLEAN DEFAULT FALSE,
    rt_ticket_found BOOLEAN DEFAULT FALSE,
    rt_ticket_id VARCHAR(50),
    rt_ticket_url TEXT,
    rt_search_error TEXT,
    
    -- Timestamps
    submitted_at TIMESTAMP,
    created_at TIMESTAMP DEFAULT NOW(),
    updated_at TIMESTAMP DEFAULT NOW(),
    
    -- Constraints
    CONSTRAINT valid_date_range CHECK (
        (report_type = 'daily' AND report_date IS NOT NULL) OR
        (report_type = 'custom' AND date_from IS NOT NULL AND date_to IS NOT NULL)
    )
);

CREATE INDEX idx_reports_date ON fim.reports(report_date);
CREATE INDEX idx_reports_date_range ON fim.reports(date_from, date_to);
CREATE INDEX idx_reports_status ON fim.reports(status);
CREATE INDEX idx_reports_type ON fim.reports(report_type);

COMMENT ON TABLE fim.reports IS 'Generated FIM reports (daily or custom date range)';

-- ============================================================================
-- 3. Correlation Groups table
-- ============================================================================

CREATE TABLE IF NOT EXISTS fim.correlation_groups (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    report_id UUID REFERENCES fim.reports(id) ON DELETE CASCADE,
    
    -- Group identification
    group_name VARCHAR(255) NOT NULL, -- e.g., "etc_yum_repos_d_modified"
    group_label VARCHAR(255) NOT NULL, -- e.g., "/etc/yum.repos.d/* - Modified"
    
    -- Pattern details
    file_pattern VARCHAR(255), -- e.g., "/etc/yum.repos.d/*"
    change_type VARCHAR(50),   -- modified, created, deleted
    package_name VARCHAR(255), -- if applicable (e.g., "kernel")
    
    -- Statistics
    server_count INTEGER DEFAULT 0,
    change_count INTEGER DEFAULT 0,
    similarity_score FLOAT DEFAULT 0.0,
    
    -- Review status
    is_known BOOLEAN DEFAULT FALSE,
    reviewed_at TIMESTAMP,
    reviewed_by UUID REFERENCES fim.users(id),
    
    created_at TIMESTAMP DEFAULT NOW()
);

CREATE INDEX idx_correlation_groups_report ON fim.correlation_groups(report_id);
CREATE INDEX idx_correlation_groups_pattern ON fim.correlation_groups(file_pattern);
CREATE INDEX idx_correlation_groups_package ON fim.correlation_groups(package_name);
CREATE INDEX idx_correlation_groups_known ON fim.correlation_groups(is_known);

COMMENT ON TABLE fim.correlation_groups IS 'Grouped changes by similarity patterns';

-- ============================================================================
-- 4. Report Changes table (links alerts to reports with analyst review)
-- ============================================================================

CREATE TABLE IF NOT EXISTS fim.report_changes (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    report_id UUID REFERENCES fim.reports(id) ON DELETE CASCADE,
    correlation_group_id UUID REFERENCES fim.correlation_groups(id) ON DELETE SET NULL,
    alert_id UUID REFERENCES fim.alerts(id) ON DELETE CASCADE,
    
    -- Change details (denormalized for reporting)
    agent_hostname VARCHAR(255),
    file_path TEXT,
    change_type VARCHAR(50),
    severity VARCHAR(20),
    
    -- RT Correlation
    matched_rt_tickets JSONB,  -- Auto-discovered tickets
    linked_rt_tickets TEXT[],  -- Manually linked ticket IDs
    rt_ticket_manually_added BOOLEAN DEFAULT FALSE,
    
    -- Analyst Review
    analyst_notes TEXT,
    is_known_change BOOLEAN DEFAULT FALSE,
    evidence_provided BOOLEAN DEFAULT FALSE,
    requires_investigation BOOLEAN DEFAULT FALSE,
    
    reviewed_at TIMESTAMP,
    reviewed_by UUID REFERENCES fim.users(id),
    created_at TIMESTAMP DEFAULT NOW(),
    
    -- Constraint: if known change, must have notes
    CONSTRAINT notes_required_for_known_changes CHECK (
        (is_known_change = FALSE) OR 
        (is_known_change = TRUE AND analyst_notes IS NOT NULL AND length(trim(analyst_notes)) > 0)
    )
);

CREATE INDEX idx_report_changes_report ON fim.report_changes(report_id);
CREATE INDEX idx_report_changes_correlation ON fim.report_changes(correlation_group_id);
CREATE INDEX idx_report_changes_alert ON fim.report_changes(alert_id);
CREATE INDEX idx_report_changes_known ON fim.report_changes(is_known_change);
CREATE INDEX idx_report_changes_investigation ON fim.report_changes(requires_investigation);

COMMENT ON TABLE fim.report_changes IS 'Individual changes in reports with analyst review data';

-- ============================================================================
-- 5. RT Ticket Cache (avoid repeated RT API calls)
-- ============================================================================

CREATE TABLE IF NOT EXISTS fim.rt_ticket_cache (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    ticket_id VARCHAR(50) UNIQUE NOT NULL,
    subject TEXT,
    status VARCHAR(50),
    queue VARCHAR(100),
    created TIMESTAMP,
    last_updated TIMESTAMP,
    keywords TEXT[], -- Extracted keywords for matching
    ticket_data JSONB, -- Full ticket details
    
    cached_at TIMESTAMP DEFAULT NOW(),
    expires_at TIMESTAMP DEFAULT NOW() + INTERVAL '1 hour' -- TTL: 1 hour
);

CREATE INDEX idx_rt_ticket_cache_ticket_id ON fim.rt_ticket_cache(ticket_id);
CREATE INDEX idx_rt_ticket_cache_keywords ON fim.rt_ticket_cache USING GIN(keywords);
CREATE INDEX idx_rt_ticket_cache_expires ON fim.rt_ticket_cache(expires_at);
CREATE INDEX idx_rt_ticket_cache_status ON fim.rt_ticket_cache(status);

COMMENT ON TABLE fim.rt_ticket_cache IS 'Cached RT ticket data to reduce API calls';

-- ============================================================================
-- 6. Scan Requests (manual scan triggers)
-- ============================================================================

CREATE TABLE IF NOT EXISTS fim.scan_requests (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    agent_id UUID REFERENCES fim.agents(id) ON DELETE CASCADE,
    requested_by UUID REFERENCES fim.users(id),
    
    status VARCHAR(20) DEFAULT 'pending' CHECK (status IN ('pending', 'acknowledged', 'completed', 'failed', 'timeout')),
    
    requested_at TIMESTAMP DEFAULT NOW(),
    acknowledged_at TIMESTAMP,
    completed_at TIMESTAMP,
    timeout_at TIMESTAMP DEFAULT NOW() + INTERVAL '1 hour', -- Auto-expire after 1 hour
    
    error_message TEXT,
    scan_id UUID, -- Links to fim.scans when completed
    
    FOREIGN KEY (scan_id) REFERENCES fim.scans(id) ON DELETE SET NULL
);

CREATE INDEX idx_scan_requests_agent ON fim.scan_requests(agent_id);
CREATE INDEX idx_scan_requests_status ON fim.scan_requests(status);
CREATE INDEX idx_scan_requests_requested_by ON fim.scan_requests(requested_by);
CREATE INDEX idx_scan_requests_timeout ON fim.scan_requests(timeout_at);

COMMENT ON TABLE fim.scan_requests IS 'Manual scan requests triggered from dashboard';

-- ============================================================================
-- 7. Enhanced Audit Logs (already exists, add new action types)
-- ============================================================================

-- Add user_agent column if not exists
ALTER TABLE fim.audit_logs ADD COLUMN IF NOT EXISTS user_agent TEXT;

-- Create index on timestamp for better query performance
CREATE INDEX IF NOT EXISTS idx_audit_logs_timestamp ON fim.audit_logs(timestamp DESC);
CREATE INDEX IF NOT EXISTS idx_audit_logs_resource ON fim.audit_logs(resource_type, resource_id);

COMMENT ON TABLE fim.audit_logs IS 'Audit trail of all user actions (login, report generation, review, etc.)';

-- ============================================================================
-- 8. Update existing tables with new columns
-- ============================================================================

-- Add agent health tracking columns if not exist
ALTER TABLE fim.agents ADD COLUMN IF NOT EXISTS last_scan_at TIMESTAMP;
ALTER TABLE fim.agents ADD COLUMN IF NOT EXISTS scan_count INTEGER DEFAULT 0;

CREATE INDEX IF NOT EXISTS idx_agents_last_scan ON fim.agents(last_scan_at);

-- ============================================================================
-- 9. Create views for easier querying
-- ============================================================================

-- View: Pending Reports
CREATE OR REPLACE VIEW fim.v_pending_reports AS
SELECT 
    r.*,
    u.username as generated_by_name,
    COUNT(DISTINCT rc.correlation_group_id) as groups_count
FROM fim.reports r
LEFT JOIN fim.users u ON r.generated_by = u.id
LEFT JOIN fim.report_changes rc ON r.id = rc.report_id
WHERE r.status IN ('pending', 'in_review')
GROUP BY r.id, u.username;

-- View: Report Summary
CREATE OR REPLACE VIEW fim.v_report_summary AS
SELECT 
    r.id,
    r.report_type,
    r.report_date,
    r.status,
    r.total_changes,
    r.known_changes,
    r.unknown_changes,
    u.username as generated_by_name,
    r.created_at,
    COUNT(DISTINCT cg.id) as correlation_groups,
    COUNT(DISTINCT rc.id) FILTER (WHERE rc.is_known_change = FALSE) as unknown_count
FROM fim.reports r
LEFT JOIN fim.users u ON r.generated_by = u.id
LEFT JOIN fim.correlation_groups cg ON r.id = cg.report_id
LEFT JOIN fim.report_changes rc ON r.id = rc.report_id
GROUP BY r.id, u.username;

-- View: Agent Health Dashboard
CREATE OR REPLACE VIEW fim.v_agent_health AS
SELECT 
    a.id,
    a.hostname,
    a.status,
    a.is_healthy,
    a.last_heartbeat,
    a.last_scan_at,
    a.scan_count,
    EXTRACT(EPOCH FROM (NOW() - a.last_scan_at))/3600 as hours_since_scan,
    CASE 
        WHEN a.last_scan_at IS NULL THEN TRUE
        WHEN EXTRACT(EPOCH FROM (NOW() - a.last_scan_at)) > 86400 THEN TRUE
        ELSE FALSE
    END as scan_needed
FROM fim.agents a;

-- ============================================================================
-- 10. Grant permissions
-- ============================================================================

-- Ensure fim schema has proper permissions
GRANT USAGE ON SCHEMA fim TO fim_user;
GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA fim TO fim_user;
GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA fim TO fim_user;
GRANT SELECT ON ALL TABLES IN SCHEMA fim TO fim_user;

-- ============================================================================
-- Migration Complete
-- ============================================================================

-- Log migration
INSERT INTO fim.audit_logs (action, resource_type, details, timestamp)
VALUES (
    'database_migration',
    'schema',
    '{"version": "001_phase1_schema", "tables_added": 5, "views_added": 3}'::jsonb,
    NOW()
);

SELECT 'Phase 1 Schema Migration Complete!' as status;
