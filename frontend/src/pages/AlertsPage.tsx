import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { fetchAlerts, bulkAlertAction, acknowledgeAlert } from "../api/dashboard";
import AlertDetailsModal from "../components/AlertDetailsModal";
import { CheckCircle, XCircle, Flag } from "lucide-react";

export default function AlertsPage() {
  const [selectedAlert, setSelectedAlert] = useState<any>(null);
  const [selectedIds, setSelectedIds] = useState<Set<string>>(new Set());
  const [bulkBusy, setBulkBusy] = useState(false);
  const [statusFilter, setStatusFilter] = useState<string>("open");
  const [severityFilter, setSeverityFilter] = useState<string>("all");
  const [sortField, setSortField] = useState<string>("detected_at");
  const [sortOrder, setSortOrder] = useState<"asc" | "desc">("desc");

  const { data, isLoading, error, refetch } = useQuery({
    queryKey: ["alerts", statusFilter],
    queryFn: () => fetchAlerts({ days: 30, limit: 1000, ...(statusFilter !== "all" ? { status: statusFilter } : {}) }),
    refetchInterval: 30_000,
  });

  if (isLoading) return <div className="text-center py-8">Loading alerts...</div>;
  if (error) return <div className="text-center py-8 text-red-400">Error loading alerts</div>;

  const alerts = data?.alerts || [];

  // Filters
  const filtered = alerts.filter((a: any) => {
    if (statusFilter !== "all" && a.status !== statusFilter) return false;
    if (severityFilter !== "all" && a.severity !== severityFilter) return false;
    return true;
  });

  // Sort
  const sortedAlerts = [...filtered].sort((a: any, b: any) => {
    let aVal = a[sortField], bVal = b[sortField];
    if (sortField === "detected_at") { aVal = aVal ? new Date(aVal).getTime() : 0; bVal = bVal ? new Date(bVal).getTime() : 0; }
    if (aVal === bVal) return 0;
    return sortOrder === "asc" ? (aVal > bVal ? 1 : -1) : (aVal < bVal ? 1 : -1);
  });

  const toggleSelect = (id: string) => {
    const next = new Set(selectedIds);
    next.has(id) ? next.delete(id) : next.add(id);
    setSelectedIds(next);
  };

  const toggleAll = () => {
    const openIds = sortedAlerts.filter((a: any) => a.status === "open").map((a: any) => a.id);
    if (selectedIds.size === openIds.length) {
      setSelectedIds(new Set());
    } else {
      setSelectedIds(new Set(openIds));
    }
  };

  const handleBulk = async (action: string) => {
    if (selectedIds.size === 0) return;
    setBulkBusy(true);
    try {
      await bulkAlertAction(Array.from(selectedIds), action);
      setSelectedIds(new Set());
      refetch();
    } catch (e: any) {
      alert("Error: " + e.message);
    } finally { setBulkBusy(false); }
  };

  const handleSort = (field: string) => {
    if (sortField === field) { setSortOrder(sortOrder === "asc" ? "desc" : "asc"); }
    else { setSortField(field); setSortOrder("desc"); }
  };

  const SortIcon = ({ field }: { field: string }) => {
    if (sortField !== field) return <span className="text-slate-600 ml-1">⇅</span>;
    return <span className="text-sky-400 ml-1">{sortOrder === "asc" ? "↑" : "↓"}</span>;
  };

  const exportToCSV = () => {
    const headers = ["Severity", "Status", "Agent", "File Path", "Detected At"];
    const rows = alerts.map((a: any) => [a.severity, a.status, a.agent_hostname, a.file_path, a.detected_at || ""]);
    const csv = [headers.join(","), ...rows.map((r: any[]) => r.map(c => `"${c}"`).join(","))].join("\n");
    const blob = new Blob([csv], { type: "text/csv" });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a"); a.href = url;
    a.download = `fim-alerts-${new Date().toISOString().split("T")[0]}.csv`;
    a.click(); URL.revokeObjectURL(url);
  };

  const openCount = sortedAlerts.filter((a: any) => a.status === "open").length;

  return (
    <div className="space-y-4">
      {/* Header */}
      <div className="flex items-center justify-between">
        <h1 className="text-xl font-semibold">
          Alerts <span className="text-slate-400 text-base">({filtered.length})</span>
        </h1>
        <div className="flex items-center gap-2">
          <button onClick={exportToCSV} disabled={alerts.length === 0}
            className="px-3 py-1.5 bg-slate-800 hover:bg-slate-700 disabled:opacity-50 rounded text-xs border border-slate-600">
            📥 Export CSV
          </button>
        </div>
      </div>

      {/* Filters */}
      <div className="flex items-center gap-3 flex-wrap">
        <select value={statusFilter} onChange={e => setStatusFilter(e.target.value)}
          className="bg-slate-800 border border-slate-700 rounded px-3 py-1.5 text-xs text-slate-300">
          <option value="all">All Status</option>
          <option value="open">Open</option>
          <option value="acknowledged">Acknowledged</option>
          <option value="resolved">Resolved</option>
          <option value="false_positive">False Positive</option>
        </select>
        <select value={severityFilter} onChange={e => setSeverityFilter(e.target.value)}
          className="bg-slate-800 border border-slate-700 rounded px-3 py-1.5 text-xs text-slate-300">
          <option value="all">All Severity</option>
          <option value="critical">Critical</option>
          <option value="high">High</option>
          <option value="medium">Medium</option>
          <option value="low">Low</option>
        </select>

        {/* Bulk Actions */}
        {selectedIds.size > 0 && (
          <div className="flex items-center gap-2 ml-4 bg-slate-800 border border-slate-700 rounded px-3 py-1.5">
            <span className="text-xs text-sky-400 font-medium">{selectedIds.size} selected</span>
            <button onClick={() => handleBulk("acknowledge")} disabled={bulkBusy}
              className="flex items-center gap-1 px-2 py-1 bg-sky-600 hover:bg-sky-500 rounded text-xs text-white disabled:opacity-50">
              <CheckCircle size={12} /> Acknowledge
            </button>
            <button onClick={() => handleBulk("resolve")} disabled={bulkBusy}
              className="flex items-center gap-1 px-2 py-1 bg-green-600 hover:bg-green-500 rounded text-xs text-white disabled:opacity-50">
              <CheckCircle size={12} /> Resolve
            </button>
            <button onClick={() => handleBulk("false_positive")} disabled={bulkBusy}
              className="flex items-center gap-1 px-2 py-1 bg-slate-600 hover:bg-slate-500 rounded text-xs text-white disabled:opacity-50">
              <Flag size={12} /> False Positive
            </button>
            <button onClick={() => setSelectedIds(new Set())} className="text-slate-400 hover:text-white text-xs ml-1">✕</button>
          </div>
        )}
      </div>

      {/* Table */}
      <div className="bg-slate-900 border border-slate-800 rounded-lg overflow-hidden">
        <table className="min-w-full text-sm">
          <thead className="bg-slate-800 text-slate-300">
            <tr>
              <th className="px-3 py-2 w-8">
                <input type="checkbox" checked={selectedIds.size > 0 && selectedIds.size === openCount}
                  onChange={toggleAll} className="accent-sky-500" title="Select all open" />
              </th>
              <th className="px-3 py-2 text-left cursor-pointer hover:bg-slate-700" onClick={() => handleSort("severity")}>
                Severity <SortIcon field="severity" />
              </th>
              <th className="px-3 py-2 text-left cursor-pointer hover:bg-slate-700" onClick={() => handleSort("status")}>
                Status <SortIcon field="status" />
              </th>
              <th className="px-3 py-2 text-left cursor-pointer hover:bg-slate-700" onClick={() => handleSort("agent_hostname")}>
                Agent <SortIcon field="agent_hostname" />
              </th>
              <th className="px-3 py-2 text-left">File</th>
              <th className="px-3 py-2 text-left cursor-pointer hover:bg-slate-700" onClick={() => handleSort("detected_at")}>
                Detected <SortIcon field="detected_at" />
              </th>
              <th className="px-3 py-2">Actions</th>
            </tr>
          </thead>
          <tbody>
            {sortedAlerts.map((a: any) => (
              <tr key={a.id} className={`border-t border-slate-800 hover:bg-slate-800/50 ${selectedIds.has(a.id) ? "bg-sky-900/20" : ""}`}>
                <td className="px-3 py-2">
                  {a.status === "open" && (
                    <input type="checkbox" checked={selectedIds.has(a.id)} onChange={() => toggleSelect(a.id)} className="accent-sky-500" />
                  )}
                </td>
                <td className="px-3 py-2">
                  <span className={`px-2 py-1 rounded-full text-xs border ${
                    a.severity === "critical" ? "bg-red-900/40 text-red-300 border-red-700"
                    : a.severity === "high" ? "bg-orange-900/40 text-orange-300 border-orange-700"
                    : a.severity === "medium" ? "bg-yellow-900/40 text-yellow-300 border-yellow-700"
                    : "bg-slate-800 text-slate-200 border-slate-600"
                  }`}>{a.severity}</span>
                </td>
                <td className="px-3 py-2">
                  <span className={`text-xs ${
                    a.status === "open" ? "text-orange-400"
                    : a.status === "acknowledged" ? "text-sky-400"
                    : a.status === "resolved" ? "text-green-400"
                    : "text-slate-400"
                  }`}>{a.status}</span>
                </td>
                <td className="px-3 py-2 text-xs text-slate-300">{a.agent_hostname}</td>
                <td className="px-3 py-2 text-xs text-slate-300 truncate max-w-xs font-mono">{a.file_path}</td>
                <td className="px-3 py-2 text-xs text-slate-400">{a.detected_at ? new Date(a.detected_at).toLocaleString() : "-"}</td>
                <td className="px-3 py-2 text-center">
                  <button onClick={() => setSelectedAlert(a)} className="text-sky-400 hover:text-sky-300 text-xs font-medium">
                    View Details
                  </button>
                </td>
              </tr>
            ))}
            {sortedAlerts.length === 0 && (
              <tr><td colSpan={7} className="px-3 py-4 text-center text-slate-400">No alerts match filters</td></tr>
            )}
          </tbody>
        </table>
      </div>

      {selectedAlert && (
        <AlertDetailsModal alert={selectedAlert} onClose={() => setSelectedAlert(null)}
          onUpdate={() => { refetch(); setSelectedAlert(null); }} />
      )}
    </div>
  );
}
