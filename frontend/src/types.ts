// ── Alert types ───────────────────────────────────────────────────────────────

export type AlertSeverity = "critical" | "high" | "medium" | "low";
export type AlertStatus   = "open" | "acknowledged" | "investigating" | "resolved" | "false_positive";

export interface AlertStats {
  total_alerts: number;
  by_status:    { open: number; acknowledged: number; resolved: number };
  by_severity:  { critical: number; high: number; medium: number; low: number };
}

// ── Agent types ───────────────────────────────────────────────────────────────

export interface Agent {
  id:             string;
  hostname:       string;
  ip_address:     string | null;
  os_type:        string | null;
  os_version:     string | null;
  agent_version:  string | null;
  status:         string;
  last_heartbeat: string | null;
  created_at:     string | null;
}

export interface AgentsListResponse {
  agents: Agent[];
  total:  number;
}

export interface HealthSummary {
  total_agents:     number;
  online_agents:    number;
  healthy_agents:   number;
  unhealthy_agents: number;
  stale_agents:     number;
}

export interface AlertsListItem {
  id:             string;
  agent_id:       string;
  agent_hostname: string;
  alert_type:     string;
  severity:       AlertSeverity;
  file_path:      string;
  status:         AlertStatus;
  change_details:  Record<string, any> | null;
  previous_state:  Record<string, any> | null;
  current_state:   Record<string, any> | null;
  detected_at:    string | null;
  created_at:     string | null;
}

// ── Report workflow types ─────────────────────────────────────────────────────

// DB CHECK constraint values for fim.reports.status
export type ReportStatus =
  | "pending"
  | "in_review"
  | "reviewed"
  | "submitted"            // published to RT successfully
  | "submitted_no_ticket"; // published but no RT ticket found

// Per-agent workflow state (fim.report_agents.status)
export type AgentWorkflowStatus = "pending" | "correlated" | "submitted" | "skipped";

export interface ReportChangeDetail {
  id:                       string;
  file_path:                string;
  agent_hostname:           string | null;
  change_type:              string | null;
  severity:                 string | null;

  // File state
  baseline_hash:            string | null;
  current_hash:             string | null;
  baseline_size:            number | null;
  current_size:             number | null;
  baseline_mtime:           string | null;
  current_mtime:            string | null;

  // Ticket linking — real DB column names
  external_ticket_id:       string | null;    // primary RT# for this change
  linked_rt_tickets:        string[];          // confirmed RT links (text[])
  matched_rt_tickets:       any | null;        // auto-matched jsonb
  rt_ticket_manually_added: boolean;

  // Review state
  analyst_notes:            string | null;
  is_known_change:          boolean;
  is_verified:              boolean;
  requires_investigation:   boolean;
}

export interface ReportTicket {
  id:          string;
  source:      "rt" | "cmr" | "jira";
  external_id: string;
  summary:     string | null;
  url:         string | null;
  is_linked:   boolean;
}

export interface ReportAgent {
  id:               string;
  agent_hostname:   string;
  ip_address:       string | null;
  correlated_rt:    string | null;
  correlated_cmr:   string | null;
  manual_rt:        string | null;
  correlation_note: string | null;
  status:           AgentWorkflowStatus;
  is_skipped:       boolean;
  skip_reason:      string | null;
  correlated_at:    string | null;
  submitted_at:     string | null;
  changes:          ReportChangeDetail[];
  tickets:          ReportTicket[];           // from fim.report_tickets
}

export interface ReportSummary {
  added_files:   number;
  removed_files: number;
  changed_files: number;
}

export interface DailyReport {
  id:               string;
  report_date:      string;
  agents:           string[];
  summary:          ReportSummary;
  status:           ReportStatus;
  total_changes:    number;
  analyst_notes:    string | null;
  created_at:       string;
  agents_total:     number;
  agents_submitted: number;         // derived: len(submitted_agents)
  published_at:     string | null;
  rt_ticket_id:     string | null;
}

export interface DailyReportDetail extends DailyReport {
  changes:            { added: string[]; removed: string[]; changed: string[] };
  details:            ReportChangeDetail[];
  report_agents:      ReportAgent[];
  correlation_run_at: string | null;
  submitted_agents:   string[];     // hostnames that have been submitted
}

export interface CorrelationSummary {
  agents_processed: number;
  rt_found:         number;
  cmr_found:        number;
  errors:           Array<{ hostname: string; error: string }>;
}

export interface PublishResult {
  success:       boolean;
  ticket_id:     string | null;
  status_to_set: string;
  message:       string;
}
