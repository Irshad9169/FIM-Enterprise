import {
  buildBuckets, buildDirectoryRollups, buildDetailEntries, dedupeByLatestMtime,
} from "../lib/reportGrouping";
import type { ReportChangeDetail } from "../types";

const CHANGE_KIND_STYLE: Record<string, { label: string; color: string }> = {
  added:   { label: "▲ Added",   color: "text-green-400" },
  removed: { label: "▼ Removed", color: "text-red-400" },
  changed: { label: "● Changed", color: "text-sky-400" },
};

/** "was changed"/"were changed", agreeing with count — not just always "were". */
function verbFor(count: number, changeType: string): string {
  const base = changeType === "changed" ? "changed" : changeType;
  return count === 1 ? `was ${base}` : `were ${base}`;
}

function BucketSection({ changes, changeType }: { changes: ReportChangeDetail[]; changeType: string }) {
  const buckets = buildBuckets(changes, changeType);
  const rollups = changeType !== "changed" ? buildDirectoryRollups(changes, changeType) : [];
  if (buckets.length === 0) return null;

  const style = CHANGE_KIND_STYLE[changeType] || { label: changeType, color: "text-slate-400" };

  return (
    <div className="px-4 pt-2 pb-2 border-t border-slate-800/60 first:border-t-0">
      <div className={`text-[11px] font-bold uppercase tracking-wider py-1.5 ${style.color}`}>
        {style.label}
      </div>

      {buckets.map(b => (
        <div key={b.category} className="pb-2 last:pb-0">
          <div className="text-[13px] text-slate-400 py-0.5 pl-1">
            <b className="text-white font-mono">{b.count}</b>{" "}
            {b.category === "other" ? "other" : `${b.category} related`}{" "}
            file{b.count === 1 ? "" : "s"} {verbFor(b.count, changeType)}
          </div>
          <div className="font-mono text-xs text-pink-400/80 pl-4 space-y-0.5">
            {b.samples.map(s => <div key={s} className="truncate">{s}</div>)}
            {b.moreCount > 0 && (
              <div className="text-slate-500 italic font-sans text-[11px]">
                + {b.moreCount} more {b.category === "other" ? "" : `${b.category}-related `}
                file{b.moreCount === 1 ? "" : "s"}
              </div>
            )}
          </div>
        </div>
      ))}

      {rollups.length > 0 && (
        <div className="font-mono text-xs text-slate-400 pl-1 pt-0.5 pb-1 space-y-0.5">
          {rollups.map(r => (
            <div key={r.directory}>
              In <span className="text-pink-400">{r.directory}</span>,{" "}
              <b className="text-white">{r.count}</b> files {verbFor(r.count, changeType)}
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

/**
 * Categorized/aggregated view of a change list — replaces the flat
 * per-file list at the volumes this report deals with (hundreds to
 * thousands of changes from a single patch). See project memory
 * "report-grouping-design-pending" for the full design rationale.
 */
export function GroupedChangesView({ changes: rawChanges }: { changes: ReportChangeDetail[] }) {
  // Same file detected more than once in one report window (e.g. /etc/shadow
  // changing twice in a day from separate password resets) collapses to one
  // entry — the latest by current_mtime — rather than being counted/shown
  // more than once.
  const changes = dedupeByLatestMtime(rawChanges);

  if (changes.length === 0) {
    return <div className="text-slate-500 text-xs italic py-4 text-center">No changes.</div>;
  }

  const changedOnly = changes.filter(c => (c.change_type || "").toLowerCase() === "changed");
  const details = buildDetailEntries(changedOnly);

  return (
    <div>
      <BucketSection changes={changes} changeType="added" />
      <BucketSection changes={changes} changeType="removed" />
      <BucketSection changes={changes} changeType="changed" />

      {details.length > 0 && (
        <div className="px-4 py-3 border-t border-slate-800/60 bg-slate-950/40">
          <div className="text-[11px] font-bold uppercase tracking-wider text-slate-400 mb-2 flex items-center justify-between gap-2 flex-wrap">
            <span>Detailed Changes — config files</span>
            <span className="text-[10px] font-normal normal-case text-slate-600 italic">
              hash still recorded per file, hidden here for readability
            </span>
          </div>
          <div className="space-y-1.5">
            {details.map(c => (
              <div key={c.id} className="font-mono text-xs border-t border-slate-800/40 pt-1.5 first:border-t-0 first:pt-0">
                <div className="text-pink-400 truncate">{c.file_path}</div>
                <div className="text-slate-500 pl-4">
                  <span className="text-green-400 font-semibold">Mtime:</span>{" "}
                  {c.baseline_mtime?.slice(0, 19) || "N/A"} → {c.current_mtime?.slice(0, 19) || "N/A"}
                </div>
                {(c.audit_uid || c.audit_process || c.audit_command) && (
                  <div className="text-slate-500 pl-4">
                    <span className="text-orange-400 font-semibold">Attributed to:</span>{" "}
                    {c.audit_process ? c.audit_process.split("/").pop() : "unknown process"}
                    {c.audit_command && c.audit_command !== c.audit_process ? ` (${c.audit_command})` : ""}
                    {c.audit_uid ? `, uid ${c.audit_uid}` : ""}
                  </div>
                )}
              </div>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}
