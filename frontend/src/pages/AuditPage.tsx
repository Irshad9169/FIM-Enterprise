import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { fetchAuditLogs, exportAuditCSV, exportAuditPDF } from "../api/dashboard";
import { formatServerDateTime } from "../lib/formatDate";
import { History, Search, ArrowLeft, X } from "lucide-react";
import { useNavigate } from "react-router-dom";

export default function AuditPage() {
  const navigate = useNavigate();
  const [search, setSearch] = useState("");

  const { data, isLoading, error } = useQuery({
    queryKey: ["audit"],
    queryFn: fetchAuditLogs,
  });

  if (isLoading) return <div className="text-center py-12 text-slate-400">Loading logs...</div>;

  if (error) return (
    <div className="p-6 text-center">
      <div className="text-red-400 mb-4">Error loading audit logs</div>
      <button
        onClick={() => navigate('/')}
        className="px-4 py-2 bg-slate-800 text-white rounded hover:bg-slate-700"
      >
        Return to Dashboard
      </button>
    </div>
  );

  // Ensure logs is an array
  const logs = Array.isArray(data) ? data : [];

  // Filter logs by search term across username, action, details, and IP
  const query = search.toLowerCase().trim();
  const filtered = query
    ? logs.filter((log: any) => {
        const username = (log.username || "").toLowerCase();
        const action = (log.action || "").toLowerCase();
        const ip = (log.ip_address || "").toLowerCase();
        const details = typeof log.details === "string"
          ? log.details.toLowerCase()
          : JSON.stringify(log.details || {}).toLowerCase();
        return (
          username.includes(query) ||
          action.includes(query) ||
          ip.includes(query) ||
          details.includes(query)
        );
      })
    : logs;

  return (
    <div className="space-y-6">
      <div className="flex justify-between items-center bg-slate-900 p-4 rounded-lg border border-slate-800">
        <div className="flex items-center gap-4">
          <button
            onClick={() => navigate('/')}
            className="p-2 bg-slate-800 rounded hover:bg-slate-700 text-slate-400 hover:text-white transition-colors"
            title="Back to Dashboard"
          >
            <ArrowLeft size={20} />
          </button>
          <div>
            <h1 className="text-xl font-bold text-white">Audit Logs</h1>
            <p className="text-slate-400 text-sm">System activity history</p>
          </div>
        </div>

        <div className="flex items-center gap-2">
          <select id="exportDays" defaultValue="30"
            className="bg-slate-950 border border-slate-700 rounded px-2 py-2 text-xs text-slate-300">
            <option value="7">Last 7 days</option>
            <option value="14">Last 14 days</option>
            <option value="30">Last 30 days</option>
            <option value="60">Last 60 days</option>
            <option value="90">Last 90 days</option>
            <option value="180">Last 180 days</option>
            <option value="365">Last 1 year</option>
          </select>
          <button onClick={() => exportAuditCSV(Number((document.getElementById("exportDays") as HTMLSelectElement).value))}
            className="px-3 py-2 bg-slate-800 hover:bg-slate-700 rounded text-xs border border-slate-700 text-slate-300">
            📥 CSV
          </button>
          <button onClick={() => exportAuditPDF(Number((document.getElementById("exportDays") as HTMLSelectElement).value))}
            className="px-3 py-2 bg-slate-800 hover:bg-slate-700 rounded text-xs border border-slate-700 text-slate-300">
            📄 PDF
          </button>
        <div className="relative">
          <Search size={16} className="absolute left-3 top-2.5 text-slate-500" />
          <input
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            placeholder="Filter by user, action, IP, details..."
            className="pl-9 pr-9 py-2 bg-slate-950 border border-slate-700 rounded text-sm text-white w-80 focus:ring-1 focus:ring-blue-500 outline-none"
          />
          {search && (
            <button
              onClick={() => setSearch("")}
              className="absolute right-2.5 top-2.5 text-slate-500 hover:text-white"
              title="Clear search"
            >
              <X size={16} />
            </button>
          )}
        </div>
        </div>
      </div>

      {/* Result count when filtering */}
      {query && (
        <div className="text-sm text-slate-400 px-1">
          Showing {filtered.length} of {logs.length} entries matching "<span className="text-blue-400">{search}</span>"
        </div>
      )}

      <div className="bg-slate-900 border border-slate-800 rounded-lg overflow-hidden">
        <table className="w-full text-sm text-left text-slate-300">
          <thead className="bg-slate-950/50 text-slate-400 font-semibold uppercase text-xs border-b border-slate-800">
            <tr>
              <th className="px-6 py-4">Time</th>
              <th className="px-6 py-4">User</th>
              <th className="px-6 py-4">Action</th>
              <th className="px-6 py-4">Details</th>
              <th className="px-6 py-4">IP Address</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-slate-800">
            {filtered.length > 0 ? filtered.map((log: any) => (
              <tr key={log.id} className="hover:bg-slate-800/50 transition-colors">
                <td className="px-6 py-4 font-mono text-xs text-slate-400">
                  {formatServerDateTime(log.created_at)}
                </td>
                <td className="px-6 py-4 font-medium text-white">
                  {log.username || 'System'}
                </td>
                <td className="px-6 py-4">
                  <span className="px-2 py-1 bg-slate-800 rounded text-xs border border-slate-700 font-medium">
                    {log.action}
                  </span>
                </td>
                <td className="px-6 py-4 text-slate-400 truncate max-w-xs" title={JSON.stringify(log.details)}>
                  {typeof log.details === 'string' ? log.details : JSON.stringify(log.details)}
                </td>
                <td className="px-6 py-4 font-mono text-xs text-slate-500">
                  {log.ip_address || '-'}
                </td>
              </tr>
            )) : (
              <tr>
                <td colSpan={5} className="px-6 py-12 text-center text-slate-500">
                  {query ? `No logs matching "${search}"` : "No audit logs found."}
                </td>
              </tr>
            )}
          </tbody>
        </table>
      </div>
    </div>
  );
}

