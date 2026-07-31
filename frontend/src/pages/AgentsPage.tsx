import { useState, useEffect } from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { fetchAgents, triggerScan, updateAgentTags, fetchAgentConfig, pushAgentConfig, pauseAgentScan, resumeAgentScan } from "../api/dashboard";
import { Tag, X, Settings, Pause, Play } from "lucide-react";

type ConfigPathRow = { path: string; exclude_patterns: string };

function ConfigEditorModal({ agentId, hostname, onClose }: {
  agentId: string; hostname: string; onClose: () => void;
}) {
  const queryClient = useQueryClient();
  const [rows, setRows] = useState<ConfigPathRow[] | null>(null);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [source, setSource] = useState<"pushed" | "reported" | null>(null);

  useEffect(() => {
    let cancelled = false;
    fetchAgentConfig(agentId).then(res => {
      if (cancelled) return;
      // Prefer desired_config (what's been pushed via this feature); fall
      // back to reported_config (what the agent says it's actually running)
      // so an agent nothing's ever been pushed to doesn't show a blank form.
      const hasPushed = res?.desired_config?.paths?.length > 0;
      const paths = hasPushed ? res.desired_config.paths : res?.reported_config?.paths;
      setSource(paths?.length ? (hasPushed ? "pushed" : "reported") : null);
      setRows(
        Array.isArray(paths) && paths.length > 0
          ? paths.map((p: any) => ({
              path: p.path || "",
              exclude_patterns: (p.exclude_patterns || []).join(", "),
            }))
          : [{ path: "", exclude_patterns: "" }],
      );
      setLoading(false);
    }).catch(() => {
      if (cancelled) return;
      setRows([{ path: "", exclude_patterns: "" }]);
      setLoading(false);
    });
    return () => { cancelled = true; };
  }, [agentId]);

  const updateRow = (i: number, field: keyof ConfigPathRow, value: string) => {
    if (!rows) return;
    const next = [...rows];
    next[i] = { ...next[i], [field]: value };
    setRows(next);
  };

  const handleSave = async () => {
    if (!rows) return;
    setSaving(true);
    try {
      const paths = rows
        .filter(r => r.path.trim())
        .map(r => ({
          path: r.path.trim(),
          exclude_patterns: r.exclude_patterns.split(",").map(p => p.trim()).filter(Boolean),
        }));
      await pushAgentConfig(agentId, paths);
      queryClient.invalidateQueries({ queryKey: ["agents"] });
      onClose();
    } catch (e: any) {
      alert(e?.message || "Failed to push config");
    } finally {
      setSaving(false);
    }
  };

  return (
    <div className="fixed inset-0 bg-black/60 flex items-center justify-center z-50 p-4" onClick={onClose}>
      <div className="bg-slate-900 border border-slate-700 rounded-lg w-full max-w-2xl p-4" onClick={e => e.stopPropagation()}>
        <div className="flex items-center justify-between mb-3">
          <h2 className="text-sm font-semibold">Monitored paths — {hostname}</h2>
          <button onClick={onClose} className="text-slate-500 hover:text-white"><X size={16} /></button>
        </div>

        <div className="text-[11px] text-slate-500 mb-1">
          Pushed here doesn't apply instantly — the agent picks it up on its next heartbeat.
        </div>
        {source && (
          <div className="text-[11px] mb-3">
            {source === "pushed" ? (
              <span className="text-sky-400">Showing the last config pushed to this agent.</span>
            ) : (
              <span className="text-amber-400">
                Nothing's been pushed yet — showing what the agent last reported it's actually monitoring.
              </span>
            )}
          </div>
        )}

        {loading || !rows ? (
          <div className="text-center text-slate-400 py-6 text-sm">Loading current config...</div>
        ) : (
          <div className="space-y-2 max-h-80 overflow-y-auto">
            {rows.map((r, i) => (
              <div key={i} className="flex gap-2 items-start">
                <input value={r.path} onChange={e => updateRow(i, "path", e.target.value)}
                  placeholder="/path/to/monitor"
                  className="flex-1 px-2 py-1.5 bg-slate-950 border border-slate-700 rounded text-xs text-white outline-none font-mono" />
                <input value={r.exclude_patterns} onChange={e => updateRow(i, "exclude_patterns", e.target.value)}
                  placeholder="exclude patterns, comma-separated"
                  className="flex-1 px-2 py-1.5 bg-slate-950 border border-slate-700 rounded text-xs text-white outline-none font-mono" />
                <button onClick={() => setRows(rows.filter((_, idx) => idx !== i))}
                  className="text-slate-500 hover:text-red-400 p-1.5"><X size={14} /></button>
              </div>
            ))}
            <button onClick={() => setRows([...rows, { path: "", exclude_patterns: "" }])}
              className="text-xs text-sky-400 hover:text-sky-300">+ Add path</button>
          </div>
        )}

        <div className="flex justify-end gap-2 mt-4 pt-3 border-t border-slate-800">
          <button onClick={onClose} className="px-3 py-1.5 text-xs rounded bg-slate-800 hover:bg-slate-700">Cancel</button>
          <button onClick={handleSave} disabled={saving || loading}
            className="px-3 py-1.5 text-xs rounded bg-sky-600 hover:bg-sky-500 disabled:bg-slate-700 disabled:text-slate-500">
            {saving ? "Pushing..." : "Push config"}
          </button>
        </div>
      </div>
    </div>
  );
}

export default function AgentsPage() {
  const [sortField, setSortField] = useState<string>("hostname");
  const [sortOrder, setSortOrder] = useState<"asc" | "desc">("asc");
  const [scanningAgent, setScanningAgent] = useState<string | null>(null);
  const [editingTags, setEditingTags] = useState<string | null>(null);
  const [tagInput, setTagInput] = useState("");
  const [configEditorAgent, setConfigEditorAgent] = useState<{ id: string; hostname: string } | null>(null);
  const queryClient = useQueryClient();

  const { data, isLoading, error } = useQuery({ queryKey: ["agents"], queryFn: fetchAgents });

  const scanMutation = useMutation({
    mutationFn: ({ agentId, force }: { agentId: string; force: boolean }) => triggerScan(agentId, force),
    onSuccess: () => { alert("Scan request sent!"); setScanningAgent(null); queryClient.invalidateQueries({ queryKey: ["agents"] }); },
    onError: (error: any, { agentId, force }) => {
      const message = error.response?.data?.detail || "Failed to trigger scan";
      if (message.includes("Wait") && !force) {
        if (confirm(`${message}\n\nForce scan anyway?`)) scanMutation.mutate({ agentId, force: true });
        else setScanningAgent(null);
      } else { alert(message); setScanningAgent(null); }
    },
  });

  const handleScan = (agentId: string) => { setScanningAgent(agentId); scanMutation.mutate({ agentId, force: false }); };

  const pauseMutation = useMutation({
    mutationFn: (agentId: string) => pauseAgentScan(agentId),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["agents"] }),
    onError: (error: any) => alert(error?.message || "Failed to pause scan"),
  });

  const resumeMutation = useMutation({
    mutationFn: (agentId: string) => resumeAgentScan(agentId),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["agents"] }),
    onError: (error: any) => alert(error?.message || "Failed to resume scan"),
  });

  const scanProgressLabel = (a: any): string | null => {
    const { scan_status, scan_progress_processed: p, scan_progress_total: t } = a;
    if (scan_status === "running") return `Scanning… ${(p ?? 0).toLocaleString()}${t ? `/${t.toLocaleString()}` : ""}`;
    if (scan_status === "paused") return `Paused at ${(p ?? 0).toLocaleString()}${t ? `/${t.toLocaleString()}` : ""}`;
    return null;
  };

  const handleSaveTags = async (agentId: string, currentTags: string[]) => {
    const newTag = tagInput.trim();
    if (newTag && !currentTags.includes(newTag)) {
      await updateAgentTags(agentId, [...currentTags, newTag]);
      queryClient.invalidateQueries({ queryKey: ["agents"] });
    }
    setTagInput("");
  };

  const handleRemoveTag = async (agentId: string, currentTags: string[], removeTag: string) => {
    await updateAgentTags(agentId, currentTags.filter(t => t !== removeTag));
    queryClient.invalidateQueries({ queryKey: ["agents"] });
  };

  if (isLoading) return <div className="text-center py-8">Loading agents...</div>;
  if (error) return <div className="text-center py-8 text-red-400">Error loading agents</div>;

  const agents = data?.agents || [];
  const sortedAgents = [...agents].sort((a: any, b: any) => {
    const aVal = a[sortField] || ""; const bVal = b[sortField] || "";
    return sortOrder === "asc" ? (aVal > bVal ? 1 : -1) : (aVal < bVal ? 1 : -1);
  });

  const handleSort = (field: string) => {
    if (sortField === field) setSortOrder(sortOrder === "asc" ? "desc" : "asc");
    else { setSortField(field); setSortOrder("asc"); }
  };

  const SortIcon = ({ field }: { field: string }) => {
    if (sortField !== field) return <span className="text-slate-600 ml-1">⇅</span>;
    return <span className="text-sky-400 ml-1">{sortOrder === "asc" ? "↑" : "↓"}</span>;
  };

  const exportToCSV = () => {
    const headers = ["Hostname", "IP Address", "Status", "Tags", "Last Heartbeat"];
    const rows = agents.map((a: any) => [a.hostname, a.ip_address || "", a.status, (a.tags || []).join(";"), a.last_heartbeat || ""]);
    const csv = [headers.join(","), ...rows.map((r: any[]) => r.map(c => `"${c}"`).join(","))].join("\n");
    const blob = new Blob([csv], { type: "text/csv" });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a"); a.href = url;
    a.download = `fim-agents-${new Date().toISOString().split("T")[0]}.csv`; a.click();
    URL.revokeObjectURL(url);
  };

  return (
    <div>
      <div className="flex items-center justify-between mb-4">
        <h1 className="text-xl font-semibold">Agents</h1>
        <button onClick={exportToCSV} className="px-4 py-2 bg-slate-800 hover:bg-slate-700 rounded text-sm border border-slate-600">📥 Export CSV</button>
      </div>

      <div className="bg-slate-900 border border-slate-800 rounded-lg overflow-hidden">
        <table className="min-w-full text-sm">
          <thead className="bg-slate-800 text-slate-300">
            <tr>
              <th className="px-3 py-2 text-left cursor-pointer hover:bg-slate-700" onClick={() => handleSort("hostname")}>Hostname <SortIcon field="hostname" /></th>
              <th className="px-3 py-2 text-left cursor-pointer hover:bg-slate-700" onClick={() => handleSort("ip_address")}>IP <SortIcon field="ip_address" /></th>
              <th className="px-3 py-2 cursor-pointer hover:bg-slate-700" onClick={() => handleSort("status")}>Status <SortIcon field="status" /></th>
              <th className="px-3 py-2 text-left">Tags</th>
              <th className="px-3 py-2">Last Heartbeat</th>
              <th className="px-3 py-2 text-center">Actions</th>
            </tr>
          </thead>
          <tbody>
            {sortedAgents.map((a: any) => {
              const tags: string[] = Array.isArray(a.tags) ? a.tags : [];
              return (
                <tr key={a.id} className="border-t border-slate-800 hover:bg-slate-800/50">
                  <td className="px-3 py-2 font-medium">{a.hostname}</td>
                  <td className="px-3 py-2 text-slate-300">{a.ip_address || "-"}</td>
                  <td className="px-3 py-2 text-center">
                    <span className={`px-2 py-1 rounded-full text-xs ${a.status === "online" ? "bg-emerald-900/40 text-emerald-300 border border-emerald-700" : "bg-slate-800 text-slate-300 border border-slate-600"}`}>
                      {a.status}
                    </span>
                  </td>
                  <td className="px-3 py-2">
                    <div className="flex flex-wrap items-center gap-1">
                      {tags.map(tag => (
                        <span key={tag} className="inline-flex items-center gap-1 px-2 py-0.5 bg-sky-900/30 text-sky-300 border border-sky-800 rounded text-[10px]">
                          {tag}
                          <button onClick={() => handleRemoveTag(a.id, tags, tag)} className="text-sky-500 hover:text-red-400"><X size={10} /></button>
                        </span>
                      ))}
                      {editingTags === a.id ? (
                        <form onSubmit={e => { e.preventDefault(); handleSaveTags(a.id, tags); }} className="inline-flex">
                          <input value={tagInput} onChange={e => setTagInput(e.target.value)} placeholder="add tag"
                            className="w-20 px-1.5 py-0.5 bg-slate-950 border border-slate-700 rounded text-[10px] text-white outline-none"
                            autoFocus onBlur={() => { if (!tagInput) setEditingTags(null); }} />
                        </form>
                      ) : (
                        <button onClick={() => { setEditingTags(a.id); setTagInput(""); }}
                          className="text-slate-500 hover:text-sky-400" title="Add tag">
                          <Tag size={12} />
                        </button>
                      )}
                    </div>
                  </td>
                  <td className="px-3 py-2 text-slate-300 text-xs text-center">{a.last_heartbeat ? new Date(a.last_heartbeat).toLocaleString() : "-"}</td>
                  <td className="px-3 py-2 text-center">
                    <div className="flex flex-col items-center gap-1">
                      {scanProgressLabel(a) && (
                        <div className={`text-[10px] font-mono ${a.scan_status === "paused" ? "text-amber-400" : "text-sky-400"}`}>
                          {scanProgressLabel(a)}
                        </div>
                      )}
                      <div className="flex items-center justify-center gap-1.5">
                        <button onClick={() => handleScan(a.id)} disabled={scanningAgent === a.id}
                          className="px-3 py-1 bg-sky-600 hover:bg-sky-500 disabled:bg-slate-700 disabled:text-slate-500 rounded text-xs font-medium transition-colors">
                          {scanningAgent === a.id ? "⏳ Scanning..." : "🔍 Scan Now"}
                        </button>
                        {a.scan_pause_requested ? (
                          <button onClick={() => resumeMutation.mutate(a.id)} disabled={resumeMutation.isPending}
                            title="Resume scan" className="p-1.5 rounded bg-emerald-900/40 hover:bg-emerald-800/60 text-emerald-300 border border-emerald-700">
                            <Play size={13} />
                          </button>
                        ) : a.scan_status === "running" ? (
                          // Only offer Pause while a scan is actually in progress —
                          // showing it unconditionally risked an accidental click
                          // silently pausing an agent that wasn't due to scan again
                          // until someone happened to notice.
                          <button onClick={() => pauseMutation.mutate(a.id)} disabled={pauseMutation.isPending}
                            title="Pause scan" className="p-1.5 rounded bg-slate-800 hover:bg-slate-700 text-slate-300">
                            <Pause size={13} />
                          </button>
                        ) : null}
                        <button onClick={() => setConfigEditorAgent({ id: a.id, hostname: a.hostname })}
                          title="Edit monitored paths"
                          className="p-1.5 rounded bg-slate-800 hover:bg-slate-700 text-slate-300">
                          <Settings size={13} />
                        </button>
                      </div>
                    </div>
                  </td>
                </tr>
              );
            })}
            {sortedAgents.length === 0 && <tr><td colSpan={6} className="px-3 py-4 text-center text-slate-400">No agents registered.</td></tr>}
          </tbody>
        </table>
      </div>

      {configEditorAgent && (
        <ConfigEditorModal
          agentId={configEditorAgent.id}
          hostname={configEditorAgent.hostname}
          onClose={() => setConfigEditorAgent(null)}
        />
      )}
    </div>
  );
}
