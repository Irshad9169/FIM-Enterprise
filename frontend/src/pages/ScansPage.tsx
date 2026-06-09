import { useState, useEffect } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { Search, Clock, FileCheck, AlertTriangle, CheckCircle, XCircle, AlertCircle, RefreshCw, Play } from "lucide-react";

const API = (path: string) => fetch(path, {
  headers: { Authorization: `Bearer ${localStorage.getItem("fim_token")}` }
});

const fetchScansAPI = async (search: string) => {
  const query = search ? `?search=${search}` : '';
  const res = await API(`/api/v1/scans${query}`);
  return res.json();
};

const triggerScan = async (agentId: string, force = false): Promise<{ ok: boolean; message: string }> => {
  const res = await fetch(`/api/v1/agents/${agentId}/scan?force=${force}`, {
    method: "POST",
    headers: {
      Authorization: `Bearer ${localStorage.getItem("fim_token")}`,
      "Content-Type": "application/json"
    }
  });
  const data = await res.json();
  if (!res.ok) return { ok: false, message: data.detail || "Failed to trigger scan" };
  return { ok: true, message: data.message || "Scan queued successfully" };
};

type Health = "healthy" | "stale" | "warning" | "critical" | "never_scanned";
type FilterVal = "all" | Health;

const healthConfig: Record<Health, { label: string; badge: string; row: string; icon: any }> = {
  healthy:      { label: "Healthy",       badge: "text-green-400 border-green-800 bg-green-900/20",    row: "",                    icon: CheckCircle  },
  stale:        { label: ">24h",          badge: "text-yellow-400 border-yellow-800 bg-yellow-900/20", row: "bg-yellow-900/10",    icon: AlertCircle  },
  warning:      { label: ">48h",          badge: "text-orange-400 border-orange-800 bg-orange-900/20", row: "bg-orange-900/10",    icon: AlertTriangle },
  critical:     { label: ">72h",          badge: "text-red-400 border-red-800 bg-red-900/20",          row: "bg-red-900/10",       icon: XCircle      },
  never_scanned:{ label: "Never Scanned", badge: "text-slate-400 border-slate-700 bg-slate-800/40",   row: "bg-slate-800/20",     icon: XCircle      },
};

const cardConfig: { key: Health; label: string; card: string }[] = [
  { key: "healthy",       label: "Healthy",       card: "border-green-800 bg-green-900/10 text-green-400 hover:bg-green-900/20"   },
  { key: "stale",         label: "Stale >24h",    card: "border-yellow-800 bg-yellow-900/10 text-yellow-400 hover:bg-yellow-900/20" },
  { key: "warning",       label: "Warning >48h",  card: "border-orange-800 bg-orange-900/10 text-orange-400 hover:bg-orange-900/20" },
  { key: "critical",      label: "Critical >72h", card: "border-red-800 bg-red-900/10 text-red-400 hover:bg-red-900/20"           },
  { key: "never_scanned", label: "Never Scanned", card: "border-slate-700 bg-slate-800/20 text-slate-400 hover:bg-slate-700/30"   },
];

export default function ScansPage() {
  const [search, setSearch]               = useState("");
  const [debouncedSearch, setDebounced]   = useState("");
  const [filter, setFilter]               = useState<FilterVal>("all");
  const [scanning, setScanning]           = useState<Record<string, "pending" | "ok" | "err">>({});
  const [toasts, setToasts]               = useState<{ id: number; msg: string; ok: boolean }[]>([]);
  const qc = useQueryClient();

  useEffect(() => {
    const t = setTimeout(() => setDebounced(search), 500);
    return () => clearTimeout(t);
  }, [search]);

  const { data, isLoading, dataUpdatedAt } = useQuery({
    queryKey: ["scans", debouncedSearch],
    queryFn: () => fetchScansAPI(debouncedSearch),
    refetchInterval: 60_000,
    placeholderData: (prev) => prev,
  });

  const allScans: any[] = data?.scans || [];
  const summary: Record<string, number> = data?.summary || {};

  const scans = filter === "all"
    ? allScans
    : allScans.filter(s => s.scan_health === filter);

  const staleCount = (summary.stale || 0) + (summary.warning || 0) +
                     (summary.critical || 0) + (summary.never_scanned || 0);

  const addToast = (msg: string, ok: boolean) => {
    const id = Date.now();
    setToasts(t => [...t, { id, msg, ok }]);
    setTimeout(() => setToasts(t => t.filter(x => x.id !== id)), 4000);
  };

  const handleScanNow = async (agentId: string, hostname: string, force = false) => {
    setScanning(s => ({ ...s, [agentId]: "pending" }));
    const result = await triggerScan(agentId, force);
    setScanning(s => ({ ...s, [agentId]: result.ok ? "ok" : "err" }));
    addToast(result.ok ? `Scan queued for ${hostname}` : `${hostname}: ${result.message}`, result.ok);
    if (result.ok) setTimeout(() => qc.invalidateQueries({ queryKey: ["scans"] }), 5000);
    setTimeout(() => setScanning(s => { const n = { ...s }; delete n[agentId]; return n; }), 3000);
  };

  const toggleFilter = (key: Health) => setFilter(f => f === key ? "all" : key);

  return (
    <div className="space-y-6">
      {/* Toast notifications */}
      <div className="fixed top-4 right-4 z-50 space-y-2">
        {toasts.map(t => (
          <div key={t.id} className={`px-4 py-3 rounded-lg border text-sm shadow-lg transition-all ${
            t.ok ? "bg-green-900/90 border-green-700 text-green-200" : "bg-red-900/90 border-red-700 text-red-200"
          }`}>
            {t.ok ? "✅" : "❌"} {t.msg}
          </div>
        ))}
      </div>

      {/* Header */}
      <div className="flex justify-between items-center bg-slate-900 p-4 rounded-lg border border-slate-800">
        <div>
          <h1 className="text-xl font-bold text-white">Scan Coverage</h1>
          <p className="text-slate-400 text-sm">
            {filter === "all" ? "All agents — latest scan status" : `Filtered: ${healthConfig[filter as Health]?.label}`}
            {dataUpdatedAt ? <span className="ml-2 text-slate-600 text-xs">· refreshed {new Date(dataUpdatedAt).toLocaleTimeString()}</span> : null}
          </p>
        </div>
        <div className="flex items-center gap-3">
          {/* Stale / All toggle */}
          <div className="flex rounded-lg overflow-hidden border border-slate-700 text-xs">
            <button onClick={() => setFilter(f => f === "all" ? "critical" : "all")}
              className={`px-3 py-2 ${filter !== "all" ? "bg-red-900/40 text-red-300" : "bg-slate-800 text-slate-400 hover:bg-slate-700"}`}>
              Stale ({staleCount})
            </button>
            <button onClick={() => setFilter("all")}
              className={`px-3 py-2 ${filter === "all" ? "bg-blue-900/40 text-blue-300" : "bg-slate-800 text-slate-400 hover:bg-slate-700"}`}>
              All ({allScans.length})
            </button>
          </div>
          {/* Refresh */}
          <button onClick={() => qc.invalidateQueries({ queryKey: ["scans"] })}
            className="p-2 rounded bg-slate-800 border border-slate-700 text-slate-400 hover:text-white hover:bg-slate-700">
            <RefreshCw size={14} />
          </button>
          {/* Search */}
          <div className="relative">
            <Search size={16} className="absolute left-3 top-2.5 text-slate-500" />
            <input
              placeholder="Search agents..."
              className="pl-9 pr-4 py-2 bg-slate-950 border border-slate-700 rounded text-sm text-white w-52 focus:ring-1 focus:ring-blue-500 outline-none"
              value={search}
              onChange={e => setSearch(e.target.value)}
            />
          </div>
        </div>
      </div>

      {/* Summary cards — clickable filters */}
      <div className="grid grid-cols-5 gap-3">
        {cardConfig.map(({ key, label, card }) => {
          const active = filter === key;
          return (
            <button key={key} onClick={() => toggleFilter(key)}
              className={`rounded-lg border p-3 text-center cursor-pointer transition-all ${card} ${
                active ? "ring-2 ring-white/30 scale-105" : ""
              }`}>
              <div className="text-2xl font-bold">{summary[key] || 0}</div>
              <div className="text-xs mt-1 opacity-80">{label}</div>
              {active && <div className="text-xs mt-1 opacity-60">click to clear</div>}
            </button>
          );
        })}
      </div>

      {/* Table */}
      <div className="bg-slate-900 border border-slate-800 rounded-lg overflow-hidden">
        <table className="w-full text-sm text-left text-slate-300">
          <thead className="bg-slate-950/50 text-slate-400 font-semibold uppercase text-xs border-b border-slate-800">
            <tr>
              <th className="px-6 py-4">Agent</th>
              <th className="px-6 py-4">Health</th>
              <th className="px-6 py-4">Files Scanned</th>
              <th className="px-6 py-4">Changes</th>
              <th className="px-6 py-4">Last Scan</th>
              <th className="px-6 py-4">Age</th>
              <th className="px-6 py-4">Action</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-slate-800">
            {scans.length > 0 ? scans.map((scan: any) => {
              const health: Health = scan.scan_health || "never_scanned";
              const cfg = healthConfig[health];
              const Icon = cfg.icon;
              const isNonHealthy = health !== "healthy";
              const scanState = scanning[scan.agent_id];

              return (
                <tr key={scan.id} className={`hover:bg-slate-800/50 ${cfg.row}`}>
                  <td className="px-6 py-4 font-medium text-white font-mono text-xs">
                    {scan.agent_hostname || scan.agent_id}
                  </td>
                  <td className="px-6 py-4">
                    <span className={`inline-flex items-center gap-1.5 px-2 py-1 rounded text-xs border ${cfg.badge}`}>
                      <Icon size={12} /> {cfg.label}
                    </span>
                  </td>
                  <td className="px-6 py-4">
                    <div className="flex items-center gap-2">
                      <FileCheck size={14} className="text-slate-500" />
                      {scan.files_scanned?.toLocaleString() || "—"}
                    </div>
                  </td>
                  <td className="px-6 py-4">
                    {(scan.files_changed || 0) > 0 ? (
                      <span className="flex items-center gap-2 text-yellow-400 font-bold">
                        <AlertTriangle size={14} /> {scan.files_changed}
                      </span>
                    ) : <span className="text-slate-500">0</span>}
                  </td>
                  <td className="px-6 py-4 text-slate-400">
                    <div className="flex items-center gap-2">
                      <Clock size={14} />
                      {scan.completed_at ? new Date(scan.completed_at).toLocaleString() : "Never"}
                    </div>
                  </td>
                  <td className="px-6 py-4">
                    {scan.hours_since_scan != null ? (
                      <span className={`font-mono text-xs ${
                        health === "critical" ? "text-red-400" :
                        health === "warning"  ? "text-orange-400" :
                        health === "stale"    ? "text-yellow-400" : "text-slate-500"
                      }`}>
                        {scan.hours_since_scan > 24
                          ? `${Math.floor(scan.hours_since_scan / 24)}d ${Math.floor(scan.hours_since_scan % 24)}h`
                          : `${scan.hours_since_scan}h`}
                      </span>
                    ) : <span className="text-slate-600">—</span>}
                  </td>
                  <td className="px-6 py-4">
                    {isNonHealthy ? (
                      <button
                        onClick={() => handleScanNow(scan.agent_id, scan.agent_hostname, true)}
                        disabled={!!scanState}
                        className={`inline-flex items-center gap-1.5 px-3 py-1.5 rounded text-xs font-medium border transition-all ${
                          scanState === "pending" ? "bg-blue-900/30 border-blue-700 text-blue-300 cursor-wait" :
                          scanState === "ok"      ? "bg-green-900/30 border-green-700 text-green-300" :
                          scanState === "err"     ? "bg-red-900/30 border-red-700 text-red-300" :
                          "bg-slate-800 border-slate-600 text-slate-300 hover:bg-blue-900/30 hover:border-blue-700 hover:text-blue-300"
                        }`}>
                        {scanState === "pending" ? <><RefreshCw size={11} className="animate-spin" /> Queuing...</> :
                         scanState === "ok"      ? <>✓ Queued</> :
                         scanState === "err"     ? <>✗ Failed</> :
                         <><Play size={11} /> Scan Now</>}
                      </button>
                    ) : (
                      <span className="text-slate-600 text-xs">—</span>
                    )}
                  </td>
                </tr>
              );
            }) : (
              <tr>
                <td colSpan={7} className="px-6 py-12 text-center text-slate-500">
                  {isLoading ? "Loading..." :
                   filter !== "all" ? `No agents with status "${healthConfig[filter as Health]?.label || filter}".` :
                   "No agents found."}
                </td>
              </tr>
            )}
          </tbody>
        </table>
      </div>
    </div>
  );
}
