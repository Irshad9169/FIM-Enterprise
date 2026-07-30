const API_BASE = "";

// GAP #13: read CSRF token from cookie
function getCsrfToken(): string {
  return document.cookie
    .split("; ")
    .find((row) => row.startsWith("csrf_token="))
    ?.split("=")[1] ?? "";
}

async function apiCall(endpoint: string, options?: RequestInit) {
  const token = localStorage.getItem("fim_token");
  const csrfToken = getCsrfToken();
  const response = await fetch(`${API_BASE}${endpoint}`, {
    ...options,
    headers: {
      Authorization:  `Bearer ${token}`,
      "Content-Type": "application/json",
      ...(csrfToken ? { "X-CSRF-Token": csrfToken } : {}),
      ...options?.headers,
    },
  });
  if (!response.ok) {
    const errorBody = await response.json().catch(() => ({}));
    throw new Error(errorBody.detail || `API call failed: ${response.statusText}`);
  }
  return response.json();
}

// ── Dashboard ─────────────────────────────────────────────────────────────────
export const fetchDashboardStats = () => apiCall("/api/v1/dashboard/stats");
export const fetchRecentAlerts   = (limit = 10) => apiCall(`/api/v1/dashboard/alerts/recent?limit=${limit}`);
export const fetchAgentHealth    = () => apiCall("/api/v1/dashboard/agents/health");
export const fetchAlertStats     = () => apiCall("/api/v1/dashboard/alerts/stats");
export const fetchHealthSummary  = () => apiCall("/api/v1/dashboard/agents/health");

// ── Agents ────────────────────────────────────────────────────────────────────
export const fetchAgents = () => apiCall("/api/v1/agents");
export const triggerScan = (agentId: string, force = false) =>
  apiCall(`/api/v1/agents/${agentId}/scan?force=${force}`, { method: "POST" });

// ── Alerts ────────────────────────────────────────────────────────────────────
export const fetchAlerts = (params?: Record<string, string>) => {
  const query = params ? `?${new URLSearchParams(params)}` : "";
  return apiCall(`/api/v1/alerts${query}`);
};

// ── Baselines ────────────────────────────────────────────────────────────────
export const fetchBaselines = () => apiCall("/api/v1/baselines");
export const deleteBaseline = (id: string) =>
  apiCall(`/api/v1/baselines/${id}`, { method: "DELETE" });

// ── Scans ────────────────────────────────────────────────────────────────────
export const fetchScans = () => apiCall("/api/v1/scans");

// ── Reports — core ───────────────────────────────────────────────────────────
export const fetchReports = (limit = 30) =>
  apiCall(`/api/v1/reports?limit=${limit}`);

export const generateReport = (reportDate: string) =>
  apiCall("/api/v1/reports/generate", {
    method: "POST",
    body:   JSON.stringify({ report_date: reportDate }),
  });

export const fetchReportDetail = (reportId: string) =>
  apiCall(`/api/v1/reports/${reportId}`);

export const deleteReport = (reportId: string) =>
  apiCall(`/api/v1/reports/${reportId}`, { method: "DELETE" });

export const updateReportStatus = (reportId: string, status: string) =>
  apiCall(`/api/v1/reports/${reportId}/status`, {
    method: "PATCH",
    body:   JSON.stringify({ status }),
  });

export const updateReportNotes = (reportId: string, notes: string) =>
  apiCall(`/api/v1/reports/${reportId}/notes`, {
    method: "PATCH",
    body:   JSON.stringify({ analyst_notes: notes }),
  });

export const exportReport = async (reportId: string): Promise<Blob> => {
  const token = localStorage.getItem("fim_token");
  const response = await fetch(`/api/v1/reports/${reportId}/export`, {
    headers: { Authorization: `Bearer ${token}` },
  });
  if (!response.ok) throw new Error("Failed to export report");
  return response.blob();
};

export const exportPdfReport = async (reportId: string): Promise<Blob> => {
  const token = localStorage.getItem("fim_token");
  const response = await fetch(`/api/v1/reports/${reportId}/export/pdf`, {
    headers: { Authorization: `Bearer ${token}` },
  });
  if (!response.ok) throw new Error("Failed to export PDF report");
  return response.blob();
};

// ── Reports — workflow ────────────────────────────────────────────────────────

/** Trigger RT + CMR correlation for all agents in a report */
export const correlateReport = (reportId: string) =>
  apiCall(`/api/v1/reports/${reportId}/correlate`, { method: "POST" });

/** On-demand ticket search for a specific agent hostname */
export const findTicketsForAgent = (reportId: string, hostname: string) =>
  apiCall(
    `/api/v1/reports/${reportId}/agents/${encodeURIComponent(hostname)}/find-tickets`
  );

/** Update RT number / CMR / note / skip flag for an agent */
export const updateReportAgent = (
  reportId: string,
  hostname: string,
  data: {
    manual_rt?:        string;
    correlated_rt?:    string;
    correlated_cmr?:   string;
    correlation_note?: string;
    is_skipped?:       boolean;
    skip_reason?:      string;
  },
) =>
  apiCall(
    `/api/v1/reports/${reportId}/agents/${encodeURIComponent(hostname)}`,
    { method: "PATCH", body: JSON.stringify(data) }
  );

/** Submit an agent as reviewed */
export const submitAgent = (
  reportId: string,
  hostname: string,
  data?: { rt_number?: string; note?: string },
) =>
  apiCall(
    `/api/v1/reports/${reportId}/agents/${encodeURIComponent(hostname)}/submit`,
    { method: "POST", body: JSON.stringify(data || {}) }
  );

/**
 * Link a file change to an RT ticket.
 * Maps to PATCH /reports/{id}/changes/{change_id}/link
 *
 * Uses real DB column names:
 *   rt_number        → external_ticket_id + appends to linked_rt_tickets[]
 *   is_known_change  → is_known_change (DB CHECK: requires analyst_notes when true)
 *   analyst_notes    → analyst_notes
 *   requires_investigation → requires_investigation
 */
export const linkChange = (
  reportId: string,
  changeId: string,
  data: {
    rt_number?:             string;
    is_known_change?:       boolean;
    analyst_notes?:         string;
    requires_investigation?: boolean;
  },
) =>
  apiCall(
    `/api/v1/reports/${reportId}/changes/${changeId}/link`,
    { method: "PATCH", body: JSON.stringify(data) }
  );

/** Publish the report to the daily RT review ticket */
export const publishReport = (reportId: string, force = false) =>
  apiCall(`/api/v1/reports/${reportId}/publish`, {
    method: "POST",
    body:   JSON.stringify({ force }),
  });

// ── Administration ────────────────────────────────────────────────────────────
export const fetchUsers  = () => apiCall("/api/v1/users");
export const createUser  = (data: Record<string, unknown>) =>
  apiCall("/api/v1/users", { method: "POST", body: JSON.stringify(data) });
export const updateUser  = (userId: string, data: Record<string, unknown>) =>
  apiCall(`/api/v1/users/${userId}`, { method: "PATCH", body: JSON.stringify(data) });
export const deleteUser  = (userId: string) =>
  apiCall(`/api/v1/users/${userId}`, { method: "DELETE" });
export const fetchAuditLogs = () => apiCall("/api/v1/audit");

export const acknowledgeAlert = (alertId: string) =>
  apiCall(`/api/v1/alerts/${alertId}/acknowledge`, { method: "PATCH" });

export const fetchTrends = (days = 30) =>
  apiCall(`/api/v1/dashboard/trends?days=${days}`);

export const fetchBaselineDiff = (baselineId: string, compareId: string) =>
  apiCall(`/api/v1/baselines/${baselineId}/diff/${compareId}`);

export const fetchBaselineDetail = (baselineId: string) =>
  apiCall(`/api/v1/baselines/${baselineId}`);

export const fetchSessions = () =>
  apiCall(`/api/v1/sessions`);

export const fetchMySessions = () =>
  apiCall(`/api/v1/sessions/me`);

export const revokeSession = (sessionId: string) =>
  apiCall(`/api/v1/sessions/${sessionId}/revoke`, { method: "POST" });

export const revokeAllUserSessions = (userId: string) =>
  apiCall(`/api/v1/sessions/user/${userId}/revoke-all`, { method: "POST" });

export const archiveReports = (days = 90) =>
  apiCall(`/api/v1/reports/archive?days=${days}`, { method: "POST" });

export const fetchArchivedReports = () =>
  apiCall(`/api/v1/reports/archived`);

export const unarchiveReport = (reportId: string) =>
  apiCall(`/api/v1/reports/${reportId}/unarchive`, { method: "POST" });

export const bulkAlertAction = (alertIds: string[], action: string) =>
  apiCall(`/api/v1/alerts/bulk`, {
    method: "PATCH",
    body: JSON.stringify({ alert_ids: alertIds, action }),
  });

export const exportAuditCSV = async (days = 30) => {
  const token = localStorage.getItem("fim_token");
  const res = await fetch(`/api/v1/audit/export/csv?days=${days}`, {
    headers: { Authorization: `Bearer ${token}` }
  });
  const blob = await res.blob();
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url; a.download = `fim-audit-${days}d.csv`; a.click();
  URL.revokeObjectURL(url);
};

export const exportAuditPDF = async (days = 30) => {
  const token = localStorage.getItem("fim_token");
  const res = await fetch(`/api/v1/audit/export/pdf?days=${days}`, {
    headers: { Authorization: `Bearer ${token}` }
  });
  const blob = await res.blob();
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url; a.download = `fim-audit-${days}d.pdf`; a.click();
  URL.revokeObjectURL(url);
};

export const updateAgentTags = (agentId: string, tags: string[]) =>
  apiCall(`/api/v1/agents/${agentId}/tags`, {
    method: "PATCH",
    body: JSON.stringify({ tags }),
  });

export const fetchAgentGroups = () =>
  apiCall(`/api/v1/agents/groups`);

export const generateComplianceReport = async (days = 30) => {
  const token = localStorage.getItem("fim_token");
  const res = await fetch(`/api/v1/reports/compliance/pci-dss?days=${days}`, {
    headers: { Authorization: `Bearer ${token}` }
  });
  const blob = await res.blob();
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url; a.download = `FIM-PCI-DSS-Compliance.pdf`; a.click();
  URL.revokeObjectURL(url);
};

export const generateSoxComplianceReport = async (days = 30) => {
  const token = localStorage.getItem("fim_token");
  const res = await fetch(`/api/v1/reports/compliance/sox?days=${days}`, {
    headers: { Authorization: `Bearer ${token}` }
  });
  const blob = await res.blob();
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url; a.download = `FIM-SOX-Compliance.pdf`; a.click();
  URL.revokeObjectURL(url);
};

export const fetchAgentDetails = () =>
  apiCall(`/api/v1/dashboard/agents/details`);

// ── Scan pause/resume ─────────────────────────────────────────────────────────
export const pauseAgentScan = (agentId: string) =>
  apiCall(`/api/v1/agents/${agentId}/pause-scan`, { method: "POST" });

export const resumeAgentScan = (agentId: string) =>
  apiCall(`/api/v1/agents/${agentId}/resume-scan`, { method: "POST" });

// ── Fleet config push ─────────────────────────────────────────────────────────
export const fetchAgentConfig = (agentId: string) =>
  apiCall(`/api/v1/agents/${agentId}/config`);

export const pushAgentConfig = (
  agentId: string,
  paths: Array<{ path: string; exclude_patterns: string[] }>,
) =>
  apiCall(`/api/v1/agents/${agentId}/config`, {
    method: "PUT",
    body: JSON.stringify({ paths }),
  });
