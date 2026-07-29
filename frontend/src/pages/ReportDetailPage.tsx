import { useParams, useNavigate } from "react-router-dom";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useState, useMemo } from "react";
import {
  fetchReportDetail, correlateReport, updateReportAgent,
  submitAgent, publishReport, updateReportNotes, updateReportStatus,
  findTicketsForAgent, linkChange, exportReport, exportPdfReport,
} from "../api/dashboard";
import type {
  DailyReportDetail, ReportAgent, ReportChangeDetail, ReportTicket,
} from "../types";
import {
  ArrowLeft, Printer, CheckCircle, RotateCcw, Send, BookOpen,
  Link as LinkIcon, Search, ChevronDown, ChevronUp, Edit2,
  SkipForward, AlertTriangle, Check, X, ExternalLink, Download, LayoutGrid, List,
} from "lucide-react";
import { GroupedChangesView } from "../components/GroupedChangesView";
import { clubHosts, dedupeByLatestMtime, type HostChanges } from "../lib/reportGrouping";

type ViewMode = "grouped" | "classic";

// ─────────────────────────────────────────────────────────────────────────────
// Helpers
// ─────────────────────────────────────────────────────────────────────────────

// Map DB status values to display colours
const REPORT_STATUS_COLORS: Record<string, string> = {
  pending:              "bg-yellow-500/20 text-yellow-400 border-yellow-500/30",
  in_review:            "bg-blue-500/20   text-blue-400   border-blue-500/30",
  reviewed:             "bg-sky-500/20    text-sky-400    border-sky-500/30",
  submitted:            "bg-green-500/20  text-green-400  border-green-500/30",
  submitted_no_ticket:  "bg-orange-500/20 text-orange-400 border-orange-500/30",
};

const AGENT_STATUS_COLORS: Record<string, string> = {
  pending:    "bg-yellow-500/20 text-yellow-400 border-yellow-500/30",
  correlated: "bg-blue-500/20   text-blue-400   border-blue-500/30",
  submitted:  "bg-green-500/20  text-green-400  border-green-500/30",
  skipped:    "bg-slate-500/20  text-slate-400  border-slate-500/30",
};

function StatusBadge({ status, map }: { status: string; map: Record<string, string> }) {
  const cls = map[status] || map.pending;
  return (
    <span className={`px-2 py-0.5 rounded border text-[10px] font-bold uppercase tracking-wider ${cls}`}>
      {status.replace(/_/g, " ")}
    </span>
  );
}

function SeverityDot({ severity }: { severity: string | null }) {
  const colors: Record<string, string> = {
    critical: "bg-red-500", high: "bg-orange-400", medium: "bg-yellow-400", low: "bg-slate-400",
  };
  return <span className={`inline-block w-2 h-2 rounded-full shrink-0 ${colors[severity ?? "medium"] ?? "bg-slate-400"}`} />;
}

// ─────────────────────────────────────────────────────────────────────────────
// Edit-Agent Modal
// ─────────────────────────────────────────────────────────────────────────────

function EditAgentModal({ agent, reportId, onClose }: { agent: ReportAgent; reportId: string; onClose: () => void }) {
  const qc = useQueryClient();
  const [rt,   setRt]   = useState(agent.manual_rt || agent.correlated_rt || "");
  const [cmr,  setCmr]  = useState(agent.correlated_cmr || "");
  const [note, setNote] = useState(agent.correlation_note || "");
  const [busy, setBusy] = useState(false);

  const save = async () => {
    setBusy(true);
    try {
      await updateReportAgent(reportId, agent.agent_hostname, {
        manual_rt:        rt   || undefined,
        correlated_cmr:   cmr  || undefined,
        correlation_note: note || undefined,
      });
      qc.invalidateQueries({ queryKey: ["report", reportId] });
      onClose();
    } finally { setBusy(false); }
  };

  return (
    <div className="fixed inset-0 bg-black/60 flex items-center justify-center z-50 p-4">
      <div className="bg-slate-900 border border-slate-700 rounded-lg w-full max-w-md shadow-2xl">
        <div className="p-4 border-b border-slate-800 flex justify-between items-center">
          <h3 className="font-bold text-white text-sm">Edit — {agent.agent_hostname}</h3>
          <button onClick={onClose}><X size={18} className="text-slate-400 hover:text-white" /></button>
        </div>
        <div className="p-4 space-y-3">
          {[["RT Ticket #", rt, setRt, "e.g. 12345"], ["CMR #", cmr, setCmr, "e.g. 123456"]].map(([label, val, setter, ph]) => (
            <div key={label as string}>
              <label className="block text-xs text-slate-400 font-bold uppercase mb-1">{label as string}</label>
              <input value={val as string} onChange={e => (setter as any)(e.target.value)} placeholder={ph as string}
                className="w-full bg-slate-950 border border-slate-700 rounded px-3 py-2 text-sm text-white outline-none focus:border-blue-500" />
            </div>
          ))}
          <div>
            <label className="block text-xs text-slate-400 font-bold uppercase mb-1">Justification Note</label>
            <textarea value={note} onChange={e => setNote(e.target.value)} rows={3}
              placeholder="Why these changes are expected / approved…"
              className="w-full bg-slate-950 border border-slate-700 rounded px-3 py-2 text-sm text-white outline-none focus:border-blue-500 resize-none" />
          </div>
        </div>
        <div className="p-4 border-t border-slate-800 flex justify-end gap-2">
          <button onClick={onClose} className="px-4 py-2 text-sm bg-slate-800 text-slate-300 rounded hover:bg-slate-700">Cancel</button>
          <button onClick={save} disabled={busy} className="px-4 py-2 text-sm bg-blue-600 text-white rounded hover:bg-blue-700 disabled:opacity-50">
            {busy ? "Saving…" : "Save"}
          </button>
        </div>
      </div>
    </div>
  );
}

// ─────────────────────────────────────────────────────────────────────────────
// Submit-Agent Modal
// ─────────────────────────────────────────────────────────────────────────────

function SubmitAgentModal({ agent, reportId, onClose }: { agent: ReportAgent; reportId: string; onClose: () => void }) {
  const qc = useQueryClient();
  const [rt,    setRt]    = useState(agent.manual_rt || agent.correlated_rt || "");
  const [note,  setNote]  = useState(agent.correlation_note || "");
  const [busy,  setBusy]  = useState(false);
  const [error, setError] = useState("");

  const doSubmit = async () => {
    setBusy(true); setError("");
    try {
      await submitAgent(reportId, agent.agent_hostname, { rt_number: rt || undefined, note: note || undefined });
      qc.invalidateQueries({ queryKey: ["report", reportId] });
      onClose();
    } catch (e: any) {
      setError(e.message || "Submit failed");
    } finally { setBusy(false); }
  };

  return (
    <div className="fixed inset-0 bg-black/60 flex items-center justify-center z-50 p-4">
      <div className="bg-slate-900 border border-slate-700 rounded-lg w-full max-w-md shadow-2xl">
        <div className="p-4 border-b border-slate-800 flex justify-between items-center">
          <h3 className="font-bold text-white text-sm flex items-center gap-2"><Send size={14} className="text-green-400" /> Submit — {agent.agent_hostname}</h3>
          <button onClick={onClose}><X size={18} className="text-slate-400 hover:text-white" /></button>
        </div>
        <div className="p-4 space-y-3">
          <p className="text-xs text-slate-400">Confirm the RT ticket and note before submitting this agent.</p>
          <div>
            <label className="block text-xs text-slate-400 font-bold uppercase mb-1">RT Ticket #</label>
            <input value={rt} onChange={e => setRt(e.target.value)} placeholder="e.g. 12345"
              className="w-full bg-slate-950 border border-slate-700 rounded px-3 py-2 text-sm text-white outline-none focus:border-blue-500" />
          </div>
          <div>
            <label className="block text-xs text-slate-400 font-bold uppercase mb-1">Note</label>
            <textarea value={note} onChange={e => setNote(e.target.value)} rows={3}
              className="w-full bg-slate-950 border border-slate-700 rounded px-3 py-2 text-sm text-white outline-none focus:border-blue-500 resize-none" />
          </div>
          {error && <div className="text-red-400 text-xs">{error}</div>}
        </div>
        <div className="p-4 border-t border-slate-800 flex justify-end gap-2">
          <button onClick={onClose} className="px-4 py-2 text-sm bg-slate-800 text-slate-300 rounded hover:bg-slate-700">Cancel</button>
          <button onClick={doSubmit} disabled={busy} className="px-4 py-2 text-sm bg-green-600 text-white rounded hover:bg-green-700 disabled:opacity-50 flex items-center gap-2">
            <Send size={14} />{busy ? "Submitting…" : "Submit"}
          </button>
        </div>
      </div>
    </div>
  );
}

// ─────────────────────────────────────────────────────────────────────────────
// Publish Modal
// ─────────────────────────────────────────────────────────────────────────────

function PublishModal({ report, onClose }: { report: DailyReportDetail; onClose: () => void }) {
  const qc = useQueryClient();
  const [force,  setForce]  = useState(false);
  const [busy,   setBusy]   = useState(false);
  const [result, setResult] = useState<{ success: boolean; message: string } | null>(null);

  const notDone = report.report_agents.filter(a => a.status !== "submitted" && a.status !== "skipped");

  const doPublish = async () => {
    setBusy(true);
    try {
      const res = await publishReport(report.id, force);
      setResult(res);
      if (res.success) qc.invalidateQueries({ queryKey: ["report", report.id] });
    } catch (e: any) {
      setResult({ success: false, message: e.message });
    } finally { setBusy(false); }
  };

  return (
    <div className="fixed inset-0 bg-black/60 flex items-center justify-center z-50 p-4">
      <div className="bg-slate-900 border border-slate-700 rounded-lg w-full max-w-lg shadow-2xl">
        <div className="p-4 border-b border-slate-800 flex justify-between items-center">
          <h3 className="font-bold text-white text-sm flex items-center gap-2"><Send size={14} className="text-green-400" /> Publish to RT</h3>
          <button onClick={onClose}><X size={18} className="text-slate-400 hover:text-white" /></button>
        </div>

        {result ? (
          <div className="p-6 text-center space-y-3">
            {result.success
              ? <CheckCircle size={48} className="text-green-400 mx-auto" />
              : <AlertTriangle size={48} className="text-orange-400 mx-auto" />}
            <p className={`text-sm font-medium ${result.success ? "text-green-300" : "text-orange-300"}`}>{result.message}</p>
            <button onClick={() => { onClose(); window.location.href = "/reports"; }} className="px-6 py-2 bg-slate-700 text-white rounded text-sm hover:bg-slate-600">Close</button>
          </div>
        ) : (
          <>
            <div className="p-4 space-y-3">
              <div className="bg-slate-950 rounded p-3 text-xs space-y-1 font-mono">
                <div className="text-slate-400">Report  : <span className="text-white">FIM-report-{report.report_date}.htm</span></div>
                <div className="text-slate-400">Agents  : <span className="text-white">{report.agents_submitted}/{report.agents_total} submitted</span></div>
                <div className="text-slate-400">Status  : <span className="text-white">{report.status}</span></div>
              </div>

              {notDone.length > 0 && (
                <div className="bg-yellow-900/20 border border-yellow-700/40 rounded p-3 space-y-1">
                  <div className="text-yellow-400 text-xs font-bold flex items-center gap-1">
                    <AlertTriangle size={12} /> {notDone.length} agent(s) not yet submitted
                  </div>
                  {notDone.map(a => (
                    <div key={a.agent_hostname} className="text-xs text-slate-400 ml-4">• {a.agent_hostname}</div>
                  ))}
                  <label className="flex items-center gap-2 mt-2 cursor-pointer">
                    <input type="checkbox" checked={force} onChange={e => setForce(e.target.checked)} className="accent-yellow-400" />
                    <span className="text-xs text-yellow-300">Force publish anyway</span>
                  </label>
                </div>
              )}

              <p className="text-xs text-slate-400">
                Posts a consolidated FIM summary comment to the daily RT review ticket for{" "}
                <span className="text-white font-mono">{report.report_date}</span>.
                If no RT ticket is found, report will be marked as <span className="text-orange-300">submitted_no_ticket</span>.
              </p>
            </div>
            <div className="p-4 border-t border-slate-800 flex justify-end gap-2">
              <button onClick={onClose} className="px-4 py-2 text-sm bg-slate-800 text-slate-300 rounded hover:bg-slate-700">Cancel</button>
              <button onClick={doPublish} disabled={busy || (notDone.length > 0 && !force)}
                className="px-4 py-2 text-sm bg-green-600 text-white rounded hover:bg-green-700 disabled:opacity-40 flex items-center gap-2">
                <Send size={14} />{busy ? "Publishing…" : "Publish"}
              </button>
            </div>
          </>
        )}
      </div>
    </div>
  );
}

// ─────────────────────────────────────────────────────────────────────────────
// File Change Row — uses real DB column names
// ─────────────────────────────────────────────────────────────────────────────

function ChangeRow({ change, reportId }: { change: ReportChangeDetail; reportId: string }) {
  const qc = useQueryClient();
  const [showLink, setShowLink] = useState(false);
  const [rtInput,  setRtInput]  = useState(change.external_ticket_id || "");
  const [note,     setNote]     = useState(change.analyst_notes || "");
  const [known,    setKnown]    = useState(change.is_known_change);
  const [busy,     setBusy]     = useState(false);

  const doLink = async () => {
    if (!change.id) return;
    if (known && !note.trim()) { alert("Analyst note is required when marking as known change (DB constraint)"); return; }
    setBusy(true);
    try {
      await linkChange(reportId, change.id, {
        rt_number:       rtInput   || undefined,
        is_known_change: known,
        analyst_notes:   note      || undefined,
      });
      qc.invalidateQueries({ queryKey: ["report", reportId] });
      setShowLink(false);
    } finally { setBusy(false); }
  };

  const isLinked = !!(change.external_ticket_id || (change.linked_rt_tickets || []).length > 0);

  return (
    <div className={`border-l-2 pl-3 py-1.5 text-xs font-mono ${
      change.requires_investigation ? "border-red-500" :
      isLinked ? "border-green-500" :
      change.is_known_change ? "border-blue-500" : "border-slate-700"}`}>
      <div className="flex items-start justify-between gap-2">
        <div className="min-w-0">
          <div className="flex items-center gap-1.5 mb-0.5 flex-wrap">
            <SeverityDot severity={change.severity} />
            <span className="text-slate-500 uppercase text-[10px]">{change.change_type}</span>
            {change.is_known_change && <span className="text-blue-400 text-[10px] font-bold">KNOWN</span>}
            {change.requires_investigation && <span className="text-red-400 text-[10px] font-bold">INVESTIGATE</span>}
            {change.external_ticket_id && (
              <a href={`https://tickets.int.untd.com/Ticket/Display.html?id=${change.external_ticket_id}`} target="_blank" rel="noopener noreferrer" className="text-green-400 text-[10px] font-bold hover:text-green-300 hover:underline">RT#{change.external_ticket_id}</a>
            )}
            {change.rt_ticket_manually_added && (
              <span className="text-slate-500 text-[10px]">(manual)</span>
            )}
          </div>
          <div className="text-pink-400 truncate">{change.file_path}</div>
          {(change.baseline_hash || change.current_hash) && (
            <div className="text-slate-600 text-[10px] mt-0.5">
              {change.baseline_hash?.slice(0, 12) || "—"} → {change.current_hash?.slice(0, 12) || "—"}
            </div>
          )}
          {change.analyst_notes && (
            <div className="text-slate-400 italic text-[10px] mt-0.5 truncate">{change.analyst_notes}</div>
          )}
        </div>
        <button onClick={() => setShowLink(p => !p)} title="Link / annotate"
          className="text-slate-600 hover:text-blue-400 shrink-0 mt-0.5">
          <LinkIcon size={12} />
        </button>
      </div>

      {showLink && (
        <div className="mt-2 space-y-1.5 border-t border-slate-800 pt-2">
          <input value={rtInput} onChange={e => setRtInput(e.target.value)} placeholder="RT # (optional)"
            className="w-full bg-slate-800 border border-slate-700 rounded px-2 py-1 text-xs text-white outline-none" />
          <textarea value={note} onChange={e => setNote(e.target.value)} rows={2}
            placeholder={`Analyst note${known ? " (required for known change)" : " (optional)"}`}
            className="w-full bg-slate-800 border border-slate-700 rounded px-2 py-1 text-xs text-white outline-none resize-none" />
          <label className="flex items-center gap-1.5 cursor-pointer">
            <input type="checkbox" checked={known} onChange={e => setKnown(e.target.checked)} className="accent-blue-400" />
            <span className="text-slate-300">Mark as known/expected change</span>
          </label>
          <div className="flex gap-1">
            <button onClick={doLink} disabled={busy}
              className="px-3 py-1 bg-blue-600 text-white rounded text-[10px] hover:bg-blue-700 disabled:opacity-50 flex items-center gap-1">
              {busy ? "…" : <><Check size={10} /> Save</>}
            </button>
            <button onClick={() => setShowLink(false)} className="px-2 py-1 text-slate-500 hover:text-white">
              <X size={12} />
            </button>
          </div>
        </div>
      )}
    </div>
  );
}

// ─────────────────────────────────────────────────────────────────────────────
// Agent Card
// ─────────────────────────────────────────────────────────────────────────────

function AgentCard({ agent, report, defaultExpanded, viewMode = "classic" }: {
  agent: ReportAgent; report: DailyReportDetail; defaultExpanded: boolean; viewMode?: ViewMode;
}) {
  const qc = useQueryClient();
  const [expanded,     setExpanded]     = useState(defaultExpanded);
  const [editModal,    setEditModal]    = useState(false);
  const [submitModal,  setSubmitModal]  = useState(false);
  const [searching,    setSearching]    = useState(false);
  const [skipping,     setSkipping]     = useState(false);

  const effectiveRt = agent.manual_rt || agent.correlated_rt;
  // Classic mode keeps the exact original raw count. Grouped mode dedupes
  // first so this number agrees with what the bucket breakdown below
  // actually shows — a file detected twice in one day is one change, not two.
  const displayChangeCount = viewMode === "grouped"
    ? dedupeByLatestMtime(agent.changes).length
    : agent.changes.length;

  const handleFindTickets = async () => {
    setSearching(true);
    try {
      await findTicketsForAgent(report.id, agent.agent_hostname);
      qc.invalidateQueries({ queryKey: ["report", report.id] });
    } finally { setSearching(false); }
  };

  const handleSkip = async () => {
    setSkipping(true);
    try {
      await updateReportAgent(report.id, agent.agent_hostname, {
        is_skipped: true, skip_reason: "Skipped by analyst",
      });
      qc.invalidateQueries({ queryKey: ["report", report.id] });
    } finally { setSkipping(false); }
  };

  const rtTickets  = agent.tickets.filter(t => t.source === "rt");
  const cmrTickets = agent.tickets.filter(t => t.source === "cmr");
  const isSubmittedInReport = (report.submitted_agents || []).includes(agent.agent_hostname);

  return (
    <>
      {editModal   && <EditAgentModal   agent={agent} reportId={report.id} onClose={() => setEditModal(false)} />}
      {submitModal && <SubmitAgentModal agent={agent} reportId={report.id} onClose={() => setSubmitModal(false)} />}

      <div className={`bg-slate-900 border rounded-lg overflow-hidden mb-3 ${
        agent.status === "submitted" ? "border-green-800/60" :
        agent.status === "skipped"  ? "border-slate-700/40" :
        agent.status === "correlated" ? "border-blue-800/40" : "border-slate-800"
      }`}>
        {/* Header */}
        <div className="p-3 bg-slate-800/50 flex items-center justify-between cursor-pointer hover:bg-slate-800 transition-colors"
          onClick={() => setExpanded(p => !p)}>
          <div className="flex items-center gap-2.5 min-w-0">
            <StatusBadge status={agent.status} map={AGENT_STATUS_COLORS} />
            <span className="font-mono font-bold text-white text-sm truncate">{agent.agent_hostname}</span>
            {agent.ip_address && <span className="text-slate-500 text-xs hidden md:block">{agent.ip_address}</span>}
            <span className="text-slate-500 text-xs">{displayChangeCount} changes</span>
            {isSubmittedInReport && <span className="text-green-400 text-xs">✓</span>}
          </div>

          <div className="flex items-center gap-1.5 shrink-0" onClick={e => e.stopPropagation()}>
            {effectiveRt && (
              <a href={`https://tickets.int.untd.com/Ticket/Display.html?id=${effectiveRt}`} target="_blank" rel="noopener noreferrer" className="text-xs bg-blue-900/40 text-blue-300 border border-blue-800/50 px-1.5 py-0.5 rounded font-mono hover:text-blue-200 hover:underline">
                RT#{effectiveRt}
              </a>
            )}
            {agent.correlated_cmr && (
              <span className="text-xs bg-cyan-900/40 text-cyan-300 border border-cyan-800/50 px-1.5 py-0.5 rounded font-mono">
                CMR#{agent.correlated_cmr}
              </span>
            )}

            {agent.status !== "submitted" && agent.status !== "skipped" && (
              <>
                <button onClick={handleFindTickets} disabled={searching} title="Search RT & CMR"
                  className="p-1.5 rounded bg-slate-700 text-cyan-400 hover:bg-cyan-900/40 disabled:opacity-50">
                  {searching ? <RotateCcw size={13} className="animate-spin" /> : <Search size={13} />}
                </button>
                <button onClick={() => setEditModal(true)} title="Edit" className="p-1.5 rounded bg-slate-700 text-slate-300 hover:bg-slate-600">
                  <Edit2 size={13} />
                </button>
                <button onClick={() => setSubmitModal(true)}
                  className="p-1.5 rounded bg-green-700 text-white hover:bg-green-600 flex items-center gap-1 text-xs px-2">
                  <Send size={12} /> Submit
                </button>
                <button onClick={handleSkip} disabled={skipping} title="Skip" className="p-1.5 rounded bg-slate-700 text-slate-400 hover:bg-slate-600 disabled:opacity-50">
                  <SkipForward size={13} />
                </button>
              </>
            )}

            {agent.status === "submitted" && <span className="text-green-400 text-xs flex items-center gap-1"><Check size={13} /> Done</span>}
            {agent.status === "skipped"   && <span className="text-slate-400 text-xs flex items-center gap-1"><SkipForward size={13} /> Skipped</span>}

            {expanded ? <ChevronUp size={15} className="text-slate-500 ml-1" /> : <ChevronDown size={15} className="text-slate-500 ml-1" />}
          </div>
        </div>

        {expanded && (
          <div className="grid grid-cols-1 lg:grid-cols-3 divide-y lg:divide-y-0 lg:divide-x divide-slate-800">
            {/* Changes */}
            <div className="lg:col-span-2 max-h-72 overflow-y-auto bg-slate-950 p-3 space-y-2">
              {viewMode === "grouped" ? (
                <GroupedChangesView changes={agent.changes} />
              ) : (
                <>
                  {agent.changes.length === 0 && (
                    <div className="text-slate-500 text-xs italic py-4 text-center">No changes for this agent.</div>
                  )}
                  {agent.changes.map((ch, idx) => (
                    <ChangeRow key={ch.id || idx} change={ch} reportId={report.id} />
                  ))}
                </>
              )}
            </div>

            {/* Tickets + note */}
            <div className="p-3 space-y-3 bg-slate-900/50">
              {agent.correlation_note && (
                <div className="bg-slate-800/50 rounded p-2 text-xs text-slate-300 italic border-l-2 border-slate-600">
                  {agent.correlation_note}
                </div>
              )}

              {rtTickets.length > 0 && (
                <div>
                  <div className="text-xs font-bold text-slate-400 uppercase mb-1 flex items-center gap-1">
                    <LinkIcon size={10} className="text-blue-400" /> RT Tickets
                  </div>
                  {rtTickets.map(t => <TicketChip key={t.external_id} ticket={t} color="blue" />)}
                </div>
              )}

              {cmrTickets.length > 0 && (
                <div>
                  <div className="text-xs font-bold text-slate-400 uppercase mb-1 flex items-center gap-1">
                    <LinkIcon size={10} className="text-cyan-400" /> CMR Tickets
                  </div>
                  {cmrTickets.map(t => <TicketChip key={t.external_id} ticket={t} color="cyan" />)}
                </div>
              )}

              {rtTickets.length === 0 && cmrTickets.length === 0 && (
                <div className="text-slate-500 text-xs italic text-center py-3">
                  No tickets found. Use <Search size={10} className="inline" /> to search.
                </div>
              )}
            </div>
          </div>
        )}
      </div>
    </>
  );
}

// ─────────────────────────────────────────────────────────────────────────────
// Host Group Card — grouped-view only. Multiple hosts sharing one
// categorized change summary (see GroupedChangesView), but each host still
// gets its own independent status/RT/submit/skip controls below — that
// workflow is a real per-host DB operation (fim.report_agents) and must
// keep working exactly as it does in AgentCard, regardless of how the
// change list itself is displayed.
// ─────────────────────────────────────────────────────────────────────────────

function HostActionRow({ agent, report }: { agent: ReportAgent; report: DailyReportDetail }) {
  const qc = useQueryClient();
  const [editModal, setEditModal] = useState(false);
  const [submitModal, setSubmitModal] = useState(false);
  const [searching, setSearching] = useState(false);

  const effectiveRt = agent.manual_rt || agent.correlated_rt;

  const handleFindTickets = async () => {
    setSearching(true);
    try {
      await findTicketsForAgent(report.id, agent.agent_hostname);
      qc.invalidateQueries({ queryKey: ["report", report.id] });
    } finally { setSearching(false); }
  };

  const handleSkip = async () => {
    await updateReportAgent(report.id, agent.agent_hostname, {
      is_skipped: true, skip_reason: "Skipped by analyst",
    });
    qc.invalidateQueries({ queryKey: ["report", report.id] });
  };

  return (
    <>
      {editModal   && <EditAgentModal   agent={agent} reportId={report.id} onClose={() => setEditModal(false)} />}
      {submitModal && <SubmitAgentModal agent={agent} reportId={report.id} onClose={() => setSubmitModal(false)} />}
      <div className="flex items-center gap-2 text-xs py-1 flex-wrap">
        <span className="font-mono font-bold text-white min-w-[15ch]">{agent.agent_hostname}</span>
        <StatusBadge status={agent.status} map={AGENT_STATUS_COLORS} />
        {effectiveRt && (
          <a href={`https://tickets.int.untd.com/Ticket/Display.html?id=${effectiveRt}`} target="_blank" rel="noopener noreferrer"
            className="text-blue-300 font-mono hover:underline">RT#{effectiveRt}</a>
        )}
        {agent.correlated_cmr && <span className="text-cyan-300 font-mono">CMR#{agent.correlated_cmr}</span>}

        {agent.status !== "submitted" && agent.status !== "skipped" && (
          <div className="flex items-center gap-1 ml-auto">
            <button onClick={handleFindTickets} disabled={searching} title="Search RT & CMR"
              className="p-1 rounded bg-slate-700 text-cyan-400 hover:bg-cyan-900/40 disabled:opacity-50">
              {searching ? <RotateCcw size={11} className="animate-spin" /> : <Search size={11} />}
            </button>
            <button onClick={() => setEditModal(true)} title="Edit" className="p-1 rounded bg-slate-700 text-slate-300 hover:bg-slate-600">
              <Edit2 size={11} />
            </button>
            <button onClick={() => setSubmitModal(true)}
              className="px-2 py-1 rounded bg-green-700 text-white hover:bg-green-600 flex items-center gap-1">
              <Send size={11} /> Submit
            </button>
            <button onClick={handleSkip} title="Skip" className="p-1 rounded bg-slate-700 text-slate-400 hover:bg-slate-600">
              <SkipForward size={11} />
            </button>
          </div>
        )}
        {agent.status === "submitted" && <span className="ml-auto text-green-400 flex items-center gap-1"><Check size={11} /> Done</span>}
        {agent.status === "skipped"   && <span className="ml-auto text-slate-400 flex items-center gap-1"><SkipForward size={11} /> Skipped</span>}
      </div>
    </>
  );
}

function HostGroupCard({ hostnames, changes, agentsByHostname, report }: {
  hostnames: string[]; changes: ReportChangeDetail[];
  agentsByHostname: Record<string, ReportAgent>; report: DailyReportDetail;
}) {
  const [expanded, setExpanded] = useState(true);

  return (
    <div className="bg-slate-900 border border-violet-800/40 rounded-lg overflow-hidden mb-3">
      <div className="p-3 bg-violet-900/10 border-b border-violet-800/30 cursor-pointer hover:bg-violet-900/20 transition-colors"
        onClick={() => setExpanded(p => !p)}>
        <div className="flex items-center justify-between flex-wrap gap-2">
          <div className="flex items-center gap-2 flex-wrap">
            <span className="text-[10px] font-bold text-violet-400 uppercase tracking-wider">
              Identical changes · {hostnames.length} hosts
            </span>
            {hostnames.map(h => (
              <span key={h} className="font-mono text-xs font-bold text-white bg-slate-950/50 border border-violet-800/40 rounded px-2 py-0.5">
                {h}
              </span>
            ))}
          </div>
          {expanded ? <ChevronUp size={15} className="text-slate-500" /> : <ChevronDown size={15} className="text-slate-500" />}
        </div>
      </div>

      {expanded && (
        <>
          <div className="p-3 bg-slate-950/30 border-b border-slate-800 space-y-1">
            {hostnames.map(h => agentsByHostname[h] && (
              <HostActionRow key={h} agent={agentsByHostname[h]} report={report} />
            ))}
          </div>
          <GroupedChangesView changes={changes} />
        </>
      )}
    </div>
  );
}

function TicketChip({ ticket, color }: { ticket: ReportTicket; color: "blue" | "cyan" }) {
  const cls = color === "blue"
    ? "border-blue-900/50 bg-blue-900/10 text-blue-400"
    : "border-cyan-900/50 bg-cyan-900/10 text-cyan-400";
  return (
    <div className={`p-2 border rounded text-xs mb-1 ${cls}`}>
      <div className="flex justify-between items-start">
        <span className="font-bold font-mono">#{ticket.external_id}</span>
        {ticket.is_linked && <Check size={10} className="text-green-400 mt-0.5" />}
      </div>
      {ticket.summary && <div className="text-slate-400 mt-0.5 text-[10px] line-clamp-2">{ticket.summary}</div>}
      {ticket.url && (
        <a href={ticket.url} target="_blank" rel="noreferrer"
          className="text-[10px] flex items-center gap-1 mt-1 hover:underline opacity-60">
          <ExternalLink size={9} /> View in {color === "blue" ? "RT" : "CMR"}
        </a>
      )}
    </div>
  );
}

// ─────────────────────────────────────────────────────────────────────────────
// Pre-correlation placeholder
// ─────────────────────────────────────────────────────────────────────────────

function PreCorrelationView({ report, viewMode }: { report: DailyReportDetail; viewMode: ViewMode }) {
  const byAgent: Record<string, typeof report.details> = {};
  for (const d of report.details) {
    const host = d.agent_hostname || "unknown";
    if (!byAgent[host]) byAgent[host] = [];
    byAgent[host].push(d);
  }

  const hostChanges: HostChanges[] = Object.entries(byAgent).map(([hostname, changes]) => ({ hostname, changes }));
  const { groups, solos } = useMemo(
    () => (viewMode === "grouped" ? clubHosts(hostChanges) : { groups: [], solos: hostChanges }),
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [viewMode, report.details],
  );

  return (
    <div className="space-y-3">
      <div className="bg-blue-900/10 border border-blue-800/40 rounded-lg p-4 flex items-start gap-3">
        <AlertTriangle size={18} className="text-yellow-400 shrink-0 mt-0.5" />
        <div>
          <div className="text-sm font-bold text-white mb-1">Correlation not yet run</div>
          <div className="text-xs text-slate-400">
            Click <strong className="text-white">Correlate All</strong> above to search RT and CMR for each agent automatically.
          </div>
        </div>
      </div>

      {viewMode === "grouped" && groups.map(g => (
        <div key={g.hostnames.join(",")} className="bg-slate-900 border border-violet-800/40 rounded-lg overflow-hidden">
          <div className="px-4 py-2 bg-violet-900/10 border-b border-violet-800/30 flex items-center gap-2 flex-wrap">
            <span className="text-[10px] font-bold text-violet-400 uppercase tracking-wider">
              Identical changes · {g.hostnames.length} hosts
            </span>
            {g.hostnames.map(h => (
              <span key={h} className="font-mono text-xs font-bold text-white bg-slate-950/50 border border-violet-800/40 rounded px-2 py-0.5">
                {h}
              </span>
            ))}
          </div>
          <GroupedChangesView changes={g.changes} />
        </div>
      ))}

      {solos.map(({ hostname, changes }) => (
        <div key={hostname} className="bg-slate-900 border border-slate-800 rounded-lg overflow-hidden">
          <div className="px-4 py-2 bg-slate-800/50 border-b border-slate-800 flex justify-between">
            <span className="font-mono font-bold text-white text-sm">{hostname}</span>
            <span className="text-slate-400 text-xs">{changes.length} changes</span>
          </div>

          {viewMode === "grouped" ? (
            <GroupedChangesView changes={changes} />
          ) : (
            <div className="divide-y divide-slate-800/50">
              {changes.map((c, idx) => (
                <div key={idx} className="px-4 py-2.5 text-xs font-mono">
                  {/* File path + type */}
                  <div className="flex items-center gap-2 mb-1.5">
                    <SeverityDot severity={c.severity} />
                    <span className="text-slate-500 uppercase w-16">{c.change_type}</span>
                    <span className="text-pink-400 truncate">{c.file_path}</span>
                  </div>
                  {/* Hash diff */}
                  {(c.baseline_hash || c.current_hash) && (
                    <div className="ml-[4.5rem] space-y-0.5 text-[10px]">
                      <div>
                        <span className="text-orange-400 font-bold">Hash: </span>
                        <span className="text-slate-500">{c.baseline_hash?.slice(0, 16) || 'N/A'}</span>
                        <span className="text-slate-600"> → </span>
                        <span className="text-slate-300">{c.current_hash?.slice(0, 16) || 'N/A'}</span>
                      </div>
                      {/* Size diff */}
                      {(c.baseline_size != null || c.current_size != null) && (
                        <div>
                          <span className="text-sky-400 font-bold">Size: </span>
                          <span className="text-slate-500">{c.baseline_size ?? 'N/A'}</span>
                          <span className="text-slate-600"> → </span>
                          <span className="text-slate-300">{c.current_size ?? 'N/A'} bytes</span>
                        </div>
                      )}
                      {/* Mtime diff */}
                      {(c.baseline_mtime || c.current_mtime) && (
                        <div>
                          <span className="text-green-400 font-bold">Mtime: </span>
                          <span className="text-slate-500">{c.baseline_mtime?.slice(0, 19) || 'N/A'}</span>
                          <span className="text-slate-600"> → </span>
                          <span className="text-slate-300">{c.current_mtime?.slice(0, 19) || 'N/A'}</span>
                        </div>
                      )}
                    </div>
                  )}
                </div>
              ))}
            </div>
          )}
        </div>
      ))}
    </div>
  );
}

// ─────────────────────────────────────────────────────────────────────────────
// Analyst Notes Panel
// ─────────────────────────────────────────────────────────────────────────────

function AnalystNotesPanel({ report }: { report: DailyReportDetail }) {
  const qc = useQueryClient();
  const [notes, setNotes] = useState(report.analyst_notes || "");
  const [busy,  setBusy]  = useState(false);
  const [saved, setSaved] = useState(false);

  const save = async () => {
    setBusy(true);
    try {
      await updateReportNotes(report.id, notes);
      qc.invalidateQueries({ queryKey: ["report", report.id] });
      setSaved(true);
      setTimeout(() => setSaved(false), 2000);
    } finally { setBusy(false); }
  };

  return (
    <div className="bg-slate-900 border border-slate-800 rounded-lg p-4">
      <h3 className="text-xs font-bold text-slate-400 uppercase mb-2 flex items-center gap-2">
        <BookOpen size={12} /> Report-Level Analyst Notes
      </h3>
      <textarea value={notes} onChange={e => setNotes(e.target.value)} rows={4}
        placeholder="Overall justification, change window, approver, ticket reference…"
        className="w-full bg-slate-950 border border-slate-800 rounded p-2 text-xs text-slate-200 outline-none resize-none focus:border-blue-500" />
      <button onClick={save} disabled={busy}
        className="mt-2 px-4 py-1.5 bg-slate-700 text-white text-xs rounded border border-slate-600 hover:bg-slate-600 disabled:opacity-50 flex items-center gap-1">
        {saved ? <><Check size={12} className="text-green-400" /> Saved!</> : busy ? "Saving…" : "Save Notes"}
      </button>
    </div>
  );
}

// ─────────────────────────────────────────────────────────────────────────────
// Main Page
// ─────────────────────────────────────────────────────────────────────────────

export default function ReportDetailPage() {
  const { reportId } = useParams<{ reportId: string }>();
  const navigate = useNavigate();
  const qc       = useQueryClient();

  const [publishModal, setPublishModal] = useState(false);
  const [correlating,  setCorrelating]  = useState(false);
  const [corrError,    setCorrError]    = useState("");
  const [exporting,    setExporting]    = useState(false);
  const [exportingPdf, setExportingPdf] = useState(false);
  // Defaults to "grouped" (the new categorized/clubbed view) — "classic" is
  // the exact pre-existing flat per-host list, kept fully intact and one
  // click away rather than deleted, precisely so this is trivially
  // reversible if the new format doesn't work out in practice.
  const [viewMode, setViewMode] = useState<ViewMode>("grouped");

  const { data: report, isLoading, error } = useQuery<DailyReportDetail>({
    queryKey: ["report", reportId],
    queryFn:  () => fetchReportDetail(reportId!),
    enabled:  !!reportId,
  });

  // These must run on every render, before any early return below — React
  // requires the same hooks in the same order every render, and `report`
  // can be undefined here while the query is still loading, so each memo
  // has to tolerate that rather than being skipped via a conditional call.
  const agentsByHostname = useMemo(() => {
    const map: Record<string, ReportAgent> = {};
    for (const a of report?.report_agents || []) map[a.agent_hostname] = a;
    return map;
  }, [report?.report_agents]);

  const { groups: hostGroups, solos: hostSolos } = useMemo(() => {
    const hasWorkflowNow = (report?.report_agents?.length ?? 0) > 0;
    if (viewMode !== "grouped" || !hasWorkflowNow || !report) {
      return { groups: [] as ReturnType<typeof clubHosts>["groups"], solos: [] as HostChanges[] };
    }
    return clubHosts(report.report_agents.map(a => ({ hostname: a.agent_hostname, changes: a.changes })));
  }, [viewMode, report?.report_agents]);

  const handleCorrelate = async () => {
    if (!reportId) return;
    setCorrelating(true); setCorrError("");
    try {
      await correlateReport(reportId);
      qc.invalidateQueries({ queryKey: ["report", reportId] });
    } catch (e: any) {
      setCorrError(e.message || "Correlation failed");
    } finally { setCorrelating(false); }
  };

  const handleExport = async () => {
    if (!reportId) return;
    setExporting(true);
    try {
      const blob = await exportReport(reportId);
      const url  = URL.createObjectURL(blob);
      const a    = document.createElement("a");
      a.href     = url;
      a.download = `FIM-report-${report?.report_date || reportId}.txt`;
      a.click();
      URL.revokeObjectURL(url);
    } finally { setExporting(false); }
  };

  const handleExportPdf = async () => {
    if (!reportId) return;
    setExportingPdf(true);
    try {
      const blob = await exportPdfReport(reportId);
      const url  = URL.createObjectURL(blob);
      const a    = document.createElement("a");
      a.href     = url;
      a.download = `FIM-report-${report?.report_date || reportId}.pdf`;
      a.click();
      URL.revokeObjectURL(url);
    } finally { setExportingPdf(false); }
  };

  if (isLoading) return (
    <div className="flex items-center justify-center h-64 text-slate-400 text-sm">
      <RotateCcw size={18} className="animate-spin mr-2" /> Loading report…
    </div>
  );
  if (error || !report) return (
    <div className="text-center py-12">
      <div className="text-red-400 font-bold mb-2">Report not found</div>
      <button onClick={() => navigate("/reports")} className="text-blue-400 text-sm hover:underline">← Back</button>
    </div>
  );

  const hasWorkflow   = report.report_agents?.length > 0;
  const submittedCount = report.agents_submitted;
  const totalCount    = report.agents_total || report.agents.length;
  const pct           = totalCount > 0 ? Math.round((submittedCount / totalCount) * 100) : 0;

  return (
    <>
      {publishModal && <PublishModal report={report} onClose={() => setPublishModal(false)} />}

      <div className="space-y-5">
        {/* Toolbar */}
        <div className="flex flex-wrap justify-between items-center gap-2 print:hidden">
          <button onClick={() => navigate("/reports")} className="px-3 py-2 bg-slate-800 text-white rounded text-sm flex items-center gap-2 hover:bg-slate-700">
            <ArrowLeft size={14} /> Back
          </button>
          <div className="flex flex-wrap gap-2">
            <div className="flex rounded overflow-hidden border border-slate-700">
              <button onClick={() => setViewMode("grouped")} title="Categorized view — grouped by pattern"
                className={`px-2.5 py-2 text-xs flex items-center gap-1.5 ${viewMode === "grouped" ? "bg-violet-700 text-white" : "bg-slate-800 text-slate-400 hover:bg-slate-700"}`}>
                <LayoutGrid size={13} /> Grouped
              </button>
              <button onClick={() => setViewMode("classic")} title="Flat per-host list — every change shown individually"
                className={`px-2.5 py-2 text-xs flex items-center gap-1.5 ${viewMode === "classic" ? "bg-slate-600 text-white" : "bg-slate-800 text-slate-400 hover:bg-slate-700"}`}>
                <List size={13} /> Classic
              </button>
            </div>
            <button onClick={handleCorrelate} disabled={correlating}
              className="px-3 py-2 bg-cyan-700 text-white text-xs rounded flex items-center gap-1.5 hover:bg-cyan-600 disabled:opacity-50">
              {correlating ? <RotateCcw size={13} className="animate-spin" /> : <Search size={13} />}
              {correlating ? "Correlating…" : "Correlate All"}
            </button>
            {report.status === "in_review" && (
              <button onClick={() => updateReportStatus(report.id, "reviewed").then(() => qc.invalidateQueries({ queryKey: ["report", reportId] }))}
                className="px-3 py-2 bg-slate-700 text-slate-200 text-xs rounded flex items-center gap-1.5 hover:bg-slate-600 border border-slate-600">
                <CheckCircle size={13} /> Mark Reviewed
              </button>
            )}
            <button onClick={handleExport} disabled={exporting} className="px-3 py-2 bg-slate-800 text-slate-200 border border-slate-700 text-xs rounded flex items-center gap-1.5 hover:bg-slate-700">
              <Download size={13} /> {exporting ? "…" : "Export TXT"}
            </button>
            <button onClick={handleExportPdf} disabled={exportingPdf} className="px-3 py-2 bg-slate-800 text-slate-200 border border-slate-700 text-xs rounded flex items-center gap-1.5 hover:bg-slate-700">
              <Download size={13} /> {exportingPdf ? "…" : "Export PDF"}
            </button>
            <button onClick={() => setPublishModal(true)} className="px-3 py-2 bg-green-700 text-white text-xs rounded flex items-center gap-1.5 hover:bg-green-600">
              <Send size={13} /> Publish to RT
            </button>
          </div>
        </div>

        {corrError && (
          <div className="bg-red-900/20 border border-red-800/50 rounded p-3 text-red-400 text-sm flex items-center gap-2">
            <AlertTriangle size={14} /> {corrError}
          </div>
        )}

        {/* Report header */}
        <div className="bg-slate-900 border border-slate-800 rounded-lg p-5">
          <div className="flex flex-wrap justify-between items-start gap-3">
            <div>
              <h1 className="text-xl font-bold text-white font-mono">FIM-report-{report.report_date}.htm</h1>
              <div className="flex items-center gap-3 mt-1.5 flex-wrap">
                <span className="text-sm text-slate-400">{report.report_date}</span>
                <StatusBadge status={report.status} map={REPORT_STATUS_COLORS} />
                {report.rt_ticket_id && (
                  <a href={`https://tickets.int.untd.com/Ticket/Display.html?id=${report.rt_ticket_id}`} target="_blank" rel="noopener noreferrer" className="text-green-300 text-xs font-mono hover:text-green-200 hover:underline">RT#{report.rt_ticket_id}</a>
                )}
              </div>
            </div>
            <div className="flex gap-5 text-center">
              <div><div className="text-2xl font-bold text-red-400">{report.total_changes}</div><div className="text-xs text-slate-500 uppercase">Alerts</div></div>
              <div><div className="text-2xl font-bold text-blue-400">{report.agents.length}</div><div className="text-xs text-slate-500 uppercase">Agents</div></div>
              {hasWorkflow && <div><div className="text-2xl font-bold text-green-400">{submittedCount}/{totalCount}</div><div className="text-xs text-slate-500 uppercase">Submitted</div></div>}
            </div>
          </div>

          {hasWorkflow && totalCount > 0 && (
            <div className="mt-4">
              <div className="flex justify-between text-xs text-slate-400 mb-1">
                <span>Review progress</span><span>{pct}%</span>
              </div>
              <div className="h-1.5 bg-slate-800 rounded-full overflow-hidden">
                <div className="h-full bg-green-500 rounded-full transition-all duration-500" style={{ width: `${pct}%` }} />
              </div>
            </div>
          )}
        </div>

        {/* Agent workflow or pre-correlation */}
        {hasWorkflow ? (
          <div>
            <h2 className="text-xs font-bold text-slate-500 uppercase tracking-wider mb-3">
              Agents ({report.report_agents.length})
            </h2>

            {viewMode === "grouped" && hostGroups.map(g => (
              <HostGroupCard key={g.hostnames.join(",")} hostnames={g.hostnames} changes={g.changes}
                agentsByHostname={agentsByHostname} report={report} />
            ))}

            {(viewMode === "grouped" ? hostSolos.map(s => agentsByHostname[s.hostname]).filter(Boolean) : report.report_agents)
              .map(agent => (
                <AgentCard key={agent.agent_hostname} agent={agent} report={report} viewMode={viewMode}
                  defaultExpanded={report.report_agents.length <= 3} />
              ))}
          </div>
        ) : (
          <PreCorrelationView report={report} viewMode={viewMode} />
        )}

        <AnalystNotesPanel report={report} />
      </div>
    </>
  );
}

