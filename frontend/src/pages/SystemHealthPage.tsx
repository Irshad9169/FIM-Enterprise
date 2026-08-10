import { useState, useEffect } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { HardDrive, Database, RefreshCw, AlertTriangle, Sliders, Check } from "lucide-react";
import { fetchDiskHealth, fetchSystemSettings, updateSystemSettings } from "../api/dashboard";
import type { DiskHealth, DiskHealthStatus, SystemSettings } from "../types";

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

function ThresholdSettings({ isAdmin }: { isAdmin: boolean }) {
  const qc = useQueryClient();
  const { data } = useQuery<SystemSettings>({
    queryKey: ["system-settings"],
    queryFn: fetchSystemSettings,
  });

  const [warning, setWarning] = useState(85);
  const [critical, setCritical] = useState(92);
  const [busy, setBusy] = useState(false);
  const [saved, setSaved] = useState(false);
  const [error, setError] = useState("");

  // Sync sliders to server values once loaded — but not on every refetch,
  // so an admin's in-progress drag isn't clobbered by a background poll.
  useEffect(() => {
    if (data) {
      setWarning(data.disk_warning_pct);
      setCritical(data.disk_critical_pct);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [data?.updated_at]);

  const invalid = warning >= critical;
  const dirty = data && (warning !== data.disk_warning_pct || critical !== data.disk_critical_pct);

  const save = async () => {
    if (invalid) return;
    setBusy(true); setError(""); setSaved(false);
    try {
      await updateSystemSettings({ disk_warning_pct: warning, disk_critical_pct: critical });
      qc.invalidateQueries({ queryKey: ["system-settings"] });
      qc.invalidateQueries({ queryKey: ["disk-health"] });
      setSaved(true);
      setTimeout(() => setSaved(false), 2000);
    } catch (e: any) {
      setError(e.message || "Failed to save thresholds");
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="bg-slate-900 border border-slate-800 rounded-lg p-5">
      <div className="flex items-center gap-2 mb-4">
        <Sliders size={16} className="text-slate-400" />
        <h2 className="text-sm font-bold text-white uppercase tracking-wider">Alert Thresholds</h2>
      </div>

      {!isAdmin && (
        <p className="text-xs text-slate-500 italic mb-3">Only admins can change these — showing current values.</p>
      )}

      <div className="space-y-5">
        <div>
          <div className="flex justify-between text-xs mb-1.5">
            <span className="text-yellow-400 font-semibold">Warning threshold</span>
            <span className="text-slate-300 font-mono">{warning}%</span>
          </div>
          <input type="range" min={1} max={98} step={1} value={warning} disabled={!isAdmin}
            onChange={e => setWarning(Number(e.target.value))}
            className="w-full accent-yellow-500 disabled:opacity-50" />
        </div>

        <div>
          <div className="flex justify-between text-xs mb-1.5">
            <span className="text-red-400 font-semibold">Critical threshold</span>
            <span className="text-slate-300 font-mono">{critical}%</span>
          </div>
          <input type="range" min={2} max={99} step={1} value={critical} disabled={!isAdmin}
            onChange={e => setCritical(Number(e.target.value))}
            className="w-full accent-red-500 disabled:opacity-50" />
        </div>

        {invalid && (
          <div className="text-xs text-red-400">Warning threshold must be lower than critical.</div>
        )}
        {error && <div className="text-xs text-red-400">{error}</div>}

        {isAdmin && (
          <button onClick={save} disabled={busy || invalid || !dirty}
            className="px-4 py-1.5 bg-slate-700 text-white text-xs rounded border border-slate-600 hover:bg-slate-600 disabled:opacity-40 flex items-center gap-1.5">
            {saved ? <><Check size={12} className="text-green-400" /> Saved!</> : busy ? "Saving…" : "Save Thresholds"}
          </button>
        )}
      </div>
    </div>
  );
}

export default function SystemHealthPage() {
  const qc = useQueryClient();
  const userRaw = localStorage.getItem("fim_user");
  const user = userRaw ? JSON.parse(userRaw) : null;
  const isAdmin = user?.role === "admin";

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

        <div className="relative h-3 bg-slate-800 rounded-full overflow-hidden mb-2">
          <div className={`h-full rounded-full transition-all duration-500 ${style.bar}`}
            style={{ width: `${disk?.used_pct ?? 0}%` }} />
          {/* Threshold markers — where the sliders below currently put warning/critical */}
          {disk && (
            <>
              <div className="absolute top-0 bottom-0 w-px bg-yellow-300/70" style={{ left: `${disk.warning_pct}%` }} title={`Warning at ${disk.warning_pct}%`} />
              <div className="absolute top-0 bottom-0 w-px bg-red-300/70" style={{ left: `${disk.critical_pct}%` }} title={`Critical at ${disk.critical_pct}%`} />
            </>
          )}
        </div>

        <div className="flex justify-between text-xs text-slate-400">
          <span>{formatBytes(disk?.used_bytes ?? 0)} used</span>
          <span className={`font-bold ${style.text}`}>{disk?.used_pct}%</span>
          <span>{formatBytes(disk?.free_bytes ?? 0)} free of {formatBytes(disk?.total_bytes ?? 0)}</span>
        </div>
      </div>

      <ThresholdSettings isAdmin={isAdmin} />

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
