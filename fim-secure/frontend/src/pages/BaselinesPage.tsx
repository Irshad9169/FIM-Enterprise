import { useState } from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { fetchBaselines, deleteBaseline, fetchBaselineDiff } from "../api/dashboard";
import { Check, ShieldCheck, Clock, Loader2, Trash2, RefreshCw, FileText, X, AlertTriangle, GitCompare } from "lucide-react";

const apiCall = async (url: string, options: RequestInit = {}) => {
  const token = localStorage.getItem("fim_token");
  const res = await fetch(url, {
    ...options,
    headers: { Authorization: `Bearer ${token}`, "Content-Type": "application/json", ...options.headers },
  });
  if (!res.ok) throw new Error(await res.text());
  return res.json();
};

export default function BaselinesPage() {
  const queryClient = useQueryClient();
  const [rebaselineTarget, setRebaselineTarget] = useState<any>(null);
  const [approveTarget, setApproveTarget] = useState<any>(null);
  const [diffPair, setDiffPair] = useState<[any, any] | null>(null);

  const { data, isLoading } = useQuery({ queryKey: ["baselines"], queryFn: fetchBaselines });

  const deleteMutation = useMutation({
    mutationFn: deleteBaseline,
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["baselines"] }),
    onError: (err) => alert("Error: " + err),
  });

  if (isLoading) return <div className="text-center py-12 text-slate-400">Loading baselines...</div>;
  const baselines = data?.baselines || [];

  const statusColors: Record<string, string> = {
    approved: "bg-green-900/30 text-green-400 border-green-800",
    pending: "bg-yellow-900/30 text-yellow-400 border-yellow-800",
    integrity_failed: "bg-red-900/30 text-red-400 border-red-800",
    superseded: "bg-slate-800 text-slate-400 border-slate-700",
    replaced: "bg-slate-800 text-slate-400 border-slate-700",
  };

  return (
    <div className="space-y-6">
      <div className="flex justify-between items-center bg-slate-900 p-4 rounded-lg border border-slate-800">
        <div>
          <h1 className="text-xl font-bold text-white">Baselines</h1>
          <p className="text-slate-400 text-sm">Approved file states for integrity comparison</p>
        </div>
      </div>

      <div className="bg-slate-900 border border-slate-800 rounded-lg overflow-hidden">
        <table className="w-full text-sm text-left text-slate-300">
          <thead className="bg-slate-950/50 text-slate-400 font-semibold uppercase text-xs border-b border-slate-800">
            <tr>
              <th className="px-6 py-4">Agent</th>
              <th className="px-6 py-4">Status</th>
              <th className="px-6 py-4">Active</th>
              <th className="px-6 py-4">Files</th>
              <th className="px-6 py-4">Created</th>
              <th className="px-6 py-4">Approved</th>
              <th className="px-6 py-4 text-right">Actions</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-slate-800">
            {baselines.map((b: any) => (
              <tr key={b.id} className="hover:bg-slate-800/50">
                <td className="px-6 py-4">
                  <div className="text-white text-xs font-medium">{b.agent_hostname}</div>
                  <div className="text-slate-500 text-[10px] font-mono">{b.agent_id.slice(0, 8)}...</div>
                </td>
                <td className="px-6 py-4">
                  <span className={`px-2 py-1 rounded text-xs border uppercase ${statusColors[b.status] || statusColors.pending}`}>
                    {b.status || "PENDING"}
                  </span>
                </td>
                <td className="px-6 py-4">
                  {b.is_active ? <ShieldCheck size={16} className="text-green-400" /> : <span className="text-slate-600">-</span>}
                </td>
                <td className="px-6 py-4 text-slate-400">{b.file_count?.toLocaleString()}</td>
                <td className="px-6 py-4 text-slate-400 text-xs">
                  <div className="flex items-center gap-1">
                    <Clock size={12} />
                    {new Date(b.created_at).toLocaleDateString()}
                  </div>
                </td>
                <td className="px-6 py-4 text-xs">
                  {b.approved_by_name ? (
                    <div>
                      <div className="text-sky-400">{b.approved_by_name}</div>
                      <div className="text-slate-500">{b.approved_at ? new Date(b.approved_at).toLocaleDateString() : ""}</div>
                    </div>
                  ) : <span className="text-slate-600">-</span>}
                </td>
                <td className="px-6 py-4 text-right">
                  <div className="flex justify-end items-center gap-2">
                    {b.status === "approved" && b.is_active && (
                      <button
                        onClick={() => setRebaselineTarget(b)}
                        className="px-3 py-1.5 bg-amber-600 text-white text-xs rounded hover:bg-amber-700 flex items-center gap-1 transition-colors"
                        title="Create new baseline from latest scan"
                      >
                        <RefreshCw size={12} /> Re-baseline
                      </button>
                    )}
                    {b.status !== "approved" && b.status !== "integrity_failed" && b.status !== "superseded" && b.status !== "replaced" && (
                      <button
                        onClick={() => setApproveTarget(b)}
                        className="px-3 py-1.5 bg-blue-600 text-white text-xs rounded hover:bg-blue-700 flex items-center gap-1 transition-colors"
                      >
                        <Check size={12} /> Approve
                      </button>
                    )}
                    {(b.status === "superseded" || b.status === "replaced") && (
                      <button
                        onClick={() => {
                          const active = baselines.find((x: any) => x.agent_id === b.agent_id && x.is_active);
                          if (active) setDiffPair([b, active]);
                          else alert("No active baseline to compare against");
                        }}
                        className="px-3 py-1.5 bg-purple-600 text-white text-xs rounded hover:bg-purple-700 flex items-center gap-1 transition-colors"
                        title="Compare with current active baseline"
                      >
                        <GitCompare size={12} /> Compare
                      </button>
                    )}
                    {!(b.is_active && b.status === "approved") && (
                      <button
                        onClick={() => { if (confirm("Delete this baseline?")) deleteMutation.mutate(b.id); }}
                        className="p-2 text-red-400 hover:bg-red-900/20 rounded transition-colors"
                        title="Delete"
                      >
                        <Trash2 size={14} />
                      </button>
                    )}
                  </div>
                </td>
              </tr>
            ))}
            {baselines.length === 0 && (
              <tr><td colSpan={7} className="px-6 py-8 text-center text-slate-500">No baselines found</td></tr>
            )}
          </tbody>
        </table>
      </div>

      {/* Re-baseline Modal */}
      {rebaselineTarget && (
        <RebaselineModal baseline={rebaselineTarget} onClose={() => setRebaselineTarget(null)}
          onSuccess={() => { setRebaselineTarget(null); queryClient.invalidateQueries({ queryKey: ["baselines"] }); }} />
      )}

      {/* Approve Modal */}
      {approveTarget && (
        <ApproveModal baseline={approveTarget} onClose={() => setApproveTarget(null)}
          onSuccess={() => { setApproveTarget(null); queryClient.invalidateQueries({ queryKey: ["baselines"] }); }} />
      )}

      {/* Diff Modal */}
      {diffPair && (
        <DiffModal baseline1={diffPair[0]} baseline2={diffPair[1]} onClose={() => setDiffPair(null)} />
      )}
    </div>
  );
}


function RebaselineModal({ baseline, onClose, onSuccess }: { baseline: any; onClose: () => void; onSuccess: () => void }) {
  const [justification, setJustification] = useState("");
  const [keepOld, setKeepOld] = useState(true);
  const [busy, setBusy] = useState(false);
  const [result, setResult] = useState<any>(null);
  const [error, setError] = useState("");

  const doRebaseline = async () => {
    if (!justification.trim()) { setError("Justification is required"); return; }
    setBusy(true);
    setError("");
    try {
      const res = await apiCall(`/api/v1/baselines/${baseline.id}/rebaseline`, {
        method: "POST",
        body: JSON.stringify({ justification, keep_old: keepOld }),
      });
      setResult(res);
    } catch (e: any) {
      setError(e.message || "Failed");
    } finally { setBusy(false); }
  };

  return (
    <div className="fixed inset-0 bg-black/60 flex items-center justify-center z-50 p-4">
      <div className="bg-slate-900 border border-slate-700 rounded-lg w-full max-w-lg shadow-2xl">
        <div className="p-4 border-b border-slate-800 flex justify-between items-center">
          <h3 className="font-bold text-white text-sm flex items-center gap-2">
            <RefreshCw size={14} className="text-amber-400" /> Re-baseline: {baseline.agent_hostname}
          </h3>
          <button onClick={onClose}><X size={18} className="text-slate-400 hover:text-white" /></button>
        </div>

        {result ? (
          <div className="p-6 text-center space-y-3">
            <Check size={48} className="text-green-400 mx-auto" />
            <p className="text-green-300 text-sm font-medium">{result.message}</p>
            <div className="text-xs text-slate-400 space-y-1">
              <div>New baseline: <span className="font-mono text-white">{result.new_baseline_id?.slice(0, 8)}...</span></div>
              <div>Files: <span className="text-white">{result.file_count?.toLocaleString()}</span></div>
            </div>
            <button onClick={onSuccess} className="px-6 py-2 bg-slate-700 text-white rounded text-sm hover:bg-slate-600">Close</button>
          </div>
        ) : (
          <>
            <div className="p-4 space-y-4">
              <div className="bg-slate-950 rounded p-3 text-xs space-y-1 font-mono">
                <div className="text-slate-400">Agent    : <span className="text-white">{baseline.agent_hostname}</span></div>
                <div className="text-slate-400">Current  : <span className="text-white">{baseline.file_count?.toLocaleString()} files</span></div>
                <div className="text-slate-400">Checksum : <span className="text-white">{baseline.checksum || "N/A"}</span></div>
              </div>

              <div className="bg-amber-900/20 border border-amber-700/40 rounded p-3">
                <div className="text-amber-400 text-xs font-bold flex items-center gap-1 mb-1">
                  <AlertTriangle size={12} /> This will replace the current active baseline
                </div>
                <p className="text-xs text-slate-400">
                  A new baseline will be created from the latest scan data.
                  It starts as <span className="text-yellow-300">pending</span> and must be approved before it becomes active.
                </p>
              </div>

              <div>
                <label className="text-xs text-slate-400 block mb-1">Justification (required)</label>
                <textarea
                  value={justification} onChange={e => setJustification(e.target.value)}
                  placeholder="e.g., Post patch window — approved server updates applied"
                  className="w-full bg-slate-950 border border-slate-700 rounded p-2 text-sm text-white placeholder-slate-600 focus:border-amber-500 focus:outline-none"
                  rows={3}
                />
              </div>

              <label className="flex items-center gap-2 cursor-pointer">
                <input type="checkbox" checked={keepOld} onChange={e => setKeepOld(e.target.checked)} className="accent-amber-400" />
                <span className="text-xs text-slate-400">Keep old baseline for audit trail</span>
              </label>

              {error && <div className="text-red-400 text-xs">{error}</div>}
            </div>

            <div className="p-4 border-t border-slate-800 flex justify-end gap-2">
              <button onClick={onClose} className="px-4 py-2 text-sm bg-slate-800 text-slate-300 rounded hover:bg-slate-700">Cancel</button>
              <button onClick={doRebaseline} disabled={busy}
                className="px-4 py-2 text-sm bg-amber-600 text-white rounded hover:bg-amber-700 disabled:opacity-40 flex items-center gap-2">
                <RefreshCw size={14} /> {busy ? "Creating…" : "Re-baseline"}
              </button>
            </div>
          </>
        )}
      </div>
    </div>
  );
}


function ApproveModal({ baseline, onClose, onSuccess }: { baseline: any; onClose: () => void; onSuccess: () => void }) {
  const [notes, setNotes] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");

  const doApprove = async () => {
    setBusy(true);
    setError("");
    try {
      await apiCall(`/api/v1/baselines/${baseline.id}/approve`, {
        method: "POST",
        body: JSON.stringify({ notes: notes || null }),
      });
      onSuccess();
    } catch (e: any) {
      setError(e.message || "Failed");
    } finally { setBusy(false); }
  };

  return (
    <div className="fixed inset-0 bg-black/60 flex items-center justify-center z-50 p-4">
      <div className="bg-slate-900 border border-slate-700 rounded-lg w-full max-w-lg shadow-2xl">
        <div className="p-4 border-b border-slate-800 flex justify-between items-center">
          <h3 className="font-bold text-white text-sm flex items-center gap-2">
            <ShieldCheck size={14} className="text-green-400" /> Approve Baseline
          </h3>
          <button onClick={onClose}><X size={18} className="text-slate-400 hover:text-white" /></button>
        </div>

        <div className="p-4 space-y-4">
          <div className="bg-slate-950 rounded p-3 text-xs space-y-1 font-mono">
            <div className="text-slate-400">Agent : <span className="text-white">{baseline.agent_hostname}</span></div>
            <div className="text-slate-400">Files : <span className="text-white">{baseline.file_count?.toLocaleString()}</span></div>
            <div className="text-slate-400">ID    : <span className="text-white">{baseline.id.slice(0, 12)}...</span></div>
          </div>

          {baseline.notes && (
            <div className="bg-slate-950 rounded p-3 text-xs">
              <div className="text-slate-500 mb-1">Notes:</div>
              <div className="text-slate-300">{baseline.notes}</div>
            </div>
          )}

          <div>
            <label className="text-xs text-slate-400 block mb-1">Approval notes (optional)</label>
            <textarea
              value={notes} onChange={e => setNotes(e.target.value)}
              placeholder="e.g., Reviewed — changes consistent with patch CHG0012345"
              className="w-full bg-slate-950 border border-slate-700 rounded p-2 text-sm text-white placeholder-slate-600 focus:border-green-500 focus:outline-none"
              rows={2}
            />
          </div>

          {error && <div className="text-red-400 text-xs">{error}</div>}
        </div>

        <div className="p-4 border-t border-slate-800 flex justify-end gap-2">
          <button onClick={onClose} className="px-4 py-2 text-sm bg-slate-800 text-slate-300 rounded hover:bg-slate-700">Cancel</button>
          <button onClick={doApprove} disabled={busy}
            className="px-4 py-2 text-sm bg-green-600 text-white rounded hover:bg-green-700 disabled:opacity-40 flex items-center gap-2">
            <Check size={14} /> {busy ? "Approving…" : "Approve"}
          </button>
        </div>
      </div>
    </div>
  );
}


function DiffModal({ baseline1, baseline2, onClose }: { baseline1: any; baseline2: any; onClose: () => void }) {
  const [diff, setDiff] = useState<any>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");

  useState(() => {
    fetchBaselineDiff(baseline1.id, baseline2.id)
      .then(d => setDiff(d))
      .catch(e => setError(e.message))
      .finally(() => setLoading(false));
  });

  return (
    <div className="fixed inset-0 bg-black/60 flex items-center justify-center z-50 p-4">
      <div className="bg-slate-900 border border-slate-700 rounded-lg w-full max-w-3xl max-h-[80vh] overflow-hidden flex flex-col shadow-2xl">
        <div className="p-4 border-b border-slate-800 flex justify-between items-center">
          <h3 className="font-bold text-white text-sm flex items-center gap-2">
            <GitCompare size={14} className="text-purple-400" /> Baseline Comparison
          </h3>
          <button onClick={onClose}><X size={18} className="text-slate-400 hover:text-white" /></button>
        </div>
        <div className="flex-1 overflow-y-auto p-4 space-y-3">
          {loading && <div className="text-center text-slate-400 py-8">Loading diff...</div>}
          {error && <div className="text-red-400 text-center py-4">{error}</div>}
          {diff && (
            <>
              <div className="grid grid-cols-3 gap-3">
                <div className="bg-green-900/20 border border-green-800 rounded p-3 text-center">
                  <div className="text-2xl font-bold text-green-400">{diff.added}</div>
                  <div className="text-xs text-green-300">Files Added</div>
                </div>
                <div className="bg-red-900/20 border border-red-800 rounded p-3 text-center">
                  <div className="text-2xl font-bold text-red-400">{diff.removed}</div>
                  <div className="text-xs text-red-300">Files Removed</div>
                </div>
                <div className="bg-orange-900/20 border border-orange-800 rounded p-3 text-center">
                  <div className="text-2xl font-bold text-orange-400">{diff.modified}</div>
                  <div className="text-xs text-orange-300">Files Modified</div>
                </div>
              </div>
              {diff.changes?.added?.length > 0 && (
                <div>
                  <h4 className="text-xs font-bold text-green-400 mb-1">Added Files</h4>
                  <div className="bg-slate-950 rounded p-2 max-h-40 overflow-y-auto">
                    {diff.changes.added.map((f: any, i: number) => (
                      <div key={i} className="text-[10px] font-mono text-green-300 py-0.5">+ {f.path}</div>
                    ))}
                  </div>
                </div>
              )}
              {diff.changes?.removed?.length > 0 && (
                <div>
                  <h4 className="text-xs font-bold text-red-400 mb-1">Removed Files</h4>
                  <div className="bg-slate-950 rounded p-2 max-h-40 overflow-y-auto">
                    {diff.changes.removed.map((f: any, i: number) => (
                      <div key={i} className="text-[10px] font-mono text-red-300 py-0.5">- {f.path}</div>
                    ))}
                  </div>
                </div>
              )}
              {diff.changes?.modified?.length > 0 && (
                <div>
                  <h4 className="text-xs font-bold text-orange-400 mb-1">Modified Files</h4>
                  <div className="bg-slate-950 rounded p-2 max-h-40 overflow-y-auto">
                    {diff.changes.modified.map((f: any, i: number) => (
                      <div key={i} className="text-[10px] font-mono text-orange-300 py-0.5">~ {f.path}</div>
                    ))}
                  </div>
                </div>
              )}
              {diff.truncated && <div className="text-yellow-400 text-xs">Results truncated to 100 per category</div>}
            </>
          )}
        </div>
        <div className="p-4 border-t border-slate-800 flex justify-end">
          <button onClick={onClose} className="px-4 py-2 bg-slate-800 text-white rounded text-sm hover:bg-slate-700">Close</button>
        </div>
      </div>
    </div>
  );
}
