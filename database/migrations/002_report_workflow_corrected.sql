-- ============================================================
-- Migration 002: Report Workflow - Corrected
-- Only adds what is genuinely missing from the existing schema.
-- Safe to run multiple times (all IF NOT EXISTS).
-- ============================================================

-- 1. Add missing columns to fim.reports
--    (analyst_notes, rt_ticket_*, submitted_agents already exist)
ALTER TABLE fim.reports
    ADD COLUMN IF NOT EXISTS correlation_run_at TIMESTAMPTZ,
    ADD COLUMN IF NOT EXISTS agents_total        INTEGER DEFAULT 0,
    ADD COLUMN IF NOT EXISTS published_at        TIMESTAMPTZ,
    ADD COLUMN IF NOT EXISTS published_by        UUID REFERENCES fim.users(id);

-- 2. Extend the status CHECK to include 'published'
--    Existing: pending / in_review / reviewed / submitted / submitted_no_ticket
--    We map our publish workflow to 'submitted' / 'submitted_no_ticket'
--    so NO constraint change is needed.
--    (kept as a comment for clarity)

-- 3. report_agents: per-agent workflow tracking
--    submitted_agents text[] on fim.reports gives us a flat hostname list,
--    but we need per-agent RT number, CMR, notes, and status.
CREATE TABLE IF NOT EXISTS fim.report_agents (
    id                  UUID            PRIMARY KEY DEFAULT gen_random_uuid(),
    report_id           UUID            NOT NULL REFERENCES fim.reports(id) ON DELETE CASCADE,
    agent_hostname      TEXT            NOT NULL,
    ip_address          TEXT,

    -- Auto-correlation results
    correlated_rt       TEXT,           -- best RT ticket number found automatically
    correlated_cmr      TEXT,           -- best CMR number found automatically

    -- Analyst overrides
    manual_rt           TEXT,           -- analyst-supplied RT override
    correlation_note    TEXT,           -- free-text justification / evidence

    -- Workflow state
    -- pending → correlated → submitted → skipped
    status              TEXT            NOT NULL DEFAULT 'pending',
    is_skipped          BOOLEAN         DEFAULT FALSE,
    skip_reason         TEXT,

    -- Timestamps
    correlated_at       TIMESTAMPTZ,
    submitted_at        TIMESTAMPTZ,
    created_at          TIMESTAMPTZ     DEFAULT NOW(),
    updated_at          TIMESTAMPTZ     DEFAULT NOW(),

    UNIQUE (report_id, agent_hostname)
);

-- 4. Indexes for report_agents
CREATE INDEX IF NOT EXISTS idx_report_agents_report    ON fim.report_agents(report_id);
CREATE INDEX IF NOT EXISTS idx_report_agents_hostname  ON fim.report_agents(agent_hostname);
CREATE INDEX IF NOT EXISTS idx_report_agents_status    ON fim.report_agents(status);

-- 5. Auto-update updated_at on report_agents
CREATE OR REPLACE FUNCTION fim.set_updated_at()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = NOW();
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS trg_report_agents_updated_at ON fim.report_agents;
CREATE TRIGGER trg_report_agents_updated_at
    BEFORE UPDATE ON fim.report_agents
    FOR EACH ROW EXECUTE FUNCTION fim.set_updated_at();

-- 6. NOTE on existing tables used as-is:
--
--    fim.rt_ticket_cache  — global RT ticket cache (by ticket_id, with TTL).
--                           We cache RT API results here, then link via report_tickets.
--
--    fim.report_tickets   — per-report/agent ticket linking.
--                           source: 'rt' | 'cmr'
--                           external_id: ticket number
--                           is_linked: true once analyst confirms
--
--    fim.report_changes   — use existing columns:
--                           external_ticket_id   → primary RT # for this change
--                           linked_rt_tickets    → text[] of confirmed RT links
--                           rt_ticket_manually_added → true when analyst adds manually
--                           analyst_notes        → per-change justification
--                           is_known_change      → mark as expected / approved
--                           (CHECK: is_known_change=true requires analyst_notes non-empty)
