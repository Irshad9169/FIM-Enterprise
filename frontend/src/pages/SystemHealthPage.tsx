import { useQuery, useQueryClient } from "@tanstack/react-query";
import { HardDrive, Database, RefreshCw, AlertTriangle } from "lucide-react";
import { fetchDiskHealth } from "../api/dashboard";
import type { DiskHealth, DiskHealthStatus } from "../types";

function formatBytes(bytes: number): string {
  if (bytes === 0) return "0 B";
  const units = ["B", "KB", "MB", "GB", "TB"];
  const i = Math.floor(Math.log(bytes) / Math.log(1024));
  return `${(bytes / Math.pow(1024, i)).toFixed(1)} ${units[i]}`;
}

const STATUS_STYLE: Record<DiskHealthStatus, { bar: string; text: string; badge: string; label: string }> = {
  ok:       { bar: "bg-green-500",  text: "text-green-400",  badge: "bg-green-900/20 border-green-800 text-green-400",   label: "Healthy" },
  warning:  { bar: "bg-yellow-500", text: "text-yellow-400", badge: "bg-yellow-900/20 border-yellow-800 text-yellow-400", label: "Warning" },
  critical: { bar: "bg-red-500",    text: "text-red-400",    badge: "bg-red-900/20 border-red-800 text-red-400 fim-attn-pulse", label: "Critical" },
};

export default function SystemHealthPage() {
  const qc = useQueryClient();

  const { data, isLoading, dataUpdatedAt } = useQuery<DiskHealth>({
    queryKey: ["disk-health"],
    queryFn: fetchDiskHealth,
    refetchInterval: 60_000,
  });

  if (isLoading) return (
    <div className="flex items-center justify-center h-64 text-slate-400 text-sm">
      <RefreshCw size={18} className="animate-spin mr-2" /> Loading system health…
    </div>
  );

  const disk = data?.disk;
  const database = data?.database;
  const style = STATUS_STYLE[disk?.status || "ok"];

  return (
    <div className="space-y-6">
      {/* Header */}
      <div className="flex justify-between items-center bg-slate-900 p-4 rounded-lg border border-slate-800">
        <div>
          <h1 className="text-xl font-bold text-white">System Health</h1>
          <p className="text-slate-400 text-sm">
            Disk usage and database table sizes
            {dataUpdatedAt ? <span className="ml-2 text-slate-600 text-xs">· refreshed {new Date(dataUpdatedAt).toLocaleTimeString()}</span> : null}
          </p>
        </div>
        <button onClick={() => qc.invalidateQueries({ queryKey: ["disk-health"] })}
          className="p-2 rounded bg-slate-800 border border-slate-700 text-slate-400 hover:text-white hover:bg-slate-700">
          <RefreshCw size={14} />
        </button>
      </div>

      {disk?.status !== "ok" && (
        <div className={`flex items-center gap-2 p-3 rounded-lg border text-sm ${style.badge}`}>
          <AlertTriangle size={16} />
          Disk usage is at <b>{disk?.used_pct}%</b> — {disk?.status === "critical"
            ? "critically low free space. Running low on headroom for database operations."
            : "getting tight. Worth investigating before it becomes critical."}
        </div>
      )}

      {/* Disk usage card */}
      <div className="bg-slate-900 border border-slate-800 rounded-lg p-5">
        <div className="flex items-center justify-between mb-3">
          <div className="flex items-center gap-2">
            <HardDrive size={16} className="text-slate-400" />
            <h2 className="text-sm font-bold text-white uppercase tracking-wider">Disk Usage</h2>
          </div>
          <span className={`px-2 py-0.5 rounded border text-[10px] font-bold uppercase tracking-wider ${style.badge}`}>
            {style.label}
          </span>
        </div>

        <div className="h-3 bg-slate-800 rounded-full overflow-hidden mb-2">
          <div className={`h-full rounded-full transition-all duration-500 ${style.bar}`}
            style={{ width: `${disk?.used_pct ?? 0}%` }} />
        </div>

        <div className="flex justify-between text-xs text-slate-400">
          <span>{formatBytes(disk?.used_bytes ?? 0)} used</span>
          <span className={`font-bold ${style.text}`}>{disk?.used_pct}%</span>
          <span>{formatBytes(disk?.free_bytes ?? 0)} free of {formatBytes(disk?.total_bytes ?? 0)}</span>
        </div>
      </div>

      {/* Database size + top tables */}
      <div className="bg-slate-900 border border-slate-800 rounded-lg p-5">
        <div className="flex items-center justify-between mb-4">
          <div className="flex items-center gap-2">
            <Database size={16} className="text-slate-400" />
            <h2 className="text-sm font-bold text-white uppercase tracking-wider">Database</h2>
          </div>
          <span className="text-sm text-slate-300 font-mono">{formatBytes(database?.total_bytes ?? 0)} total</span>
        </div>

        <table className="w-full text-sm">
          <thead>
            <tr className="text-left text-xs text-slate-500 uppercase tracking-wider border-b border-slate-800">
              <th className="pb-2 font-medium">Table</th>
              <th className="pb-2 font-medium text-right">Table Size</th>
              <th className="pb-2 font-medium text-right">Total (incl. indexes/TOAST)</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-slate-800/60">
            {(database?.top_tables || []).map(t => (
              <tr key={t.name}>
                <td className="py-2 font-mono text-pink-400">{t.name}</td>
                <td className="py-2 text-right text-slate-400 font-mono">{formatBytes(t.table_bytes)}</td>
                <td className="py-2 text-right text-white font-mono font-semibold">{formatBytes(t.total_bytes)}</td>
              </tr>
            ))}
            {(!database?.top_tables || database.top_tables.length === 0) && (
              <tr><td colSpan={3} className="py-4 text-center text-slate-500 italic">No table data available.</td></tr>
            )}
          </tbody>
        </table>
      </div>
    </div>
  );
}
