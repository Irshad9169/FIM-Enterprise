import {
  buildBuckets, buildDirectoryRollups, buildDetailEntries,
} from "../lib/reportGrouping";
import type { ReportChangeDetail } from "../types";

const CHANGE_KIND_STYLE: Record<string, { label: string; color: string }> = {
  added:   { label: "▲ Added",   color: "text-green-400" },
  removed: { label: "▼ Removed", color: "text-red-400" },
  changed: { label: "● Changed", color: "text-sky-400" },
};

function BucketSection({ changes, changeType }: { changes: ReportChangeDetail[]; changeType: string }) {
  const buckets = buildBuckets(changes, changeType);
  const rollups = changeType !== "changed" ? buildDirectoryRollups(changes, changeType) : [];
  if (buckets.length === 0) return null;

  const style = CHANGE_KIND_STYLE[changeType] || { label: changeType, color: "text-slate-400" };
  const verb = changeType === "changed" ? "were changed" : `were ${changeType}`;

  return (
    <div className="px-4 pt-2 pb-2 border-t border-slate-800/60 first:border-t-0">
      <div className={`text-[11px] font-bold uppercase tracking-wider py-1.5 ${style.color}`}>
        {style.label}
      </div>

      {buckets.map(b => (
        <div key={b.category} className="text-[13px] text-slate-400 py-0.5 pl-1">
          <b className="text-white font-mono">{b.count}</b>{" "}
          {b.category === "other" ? "other" : `${b.category} related`}{" "}
          file{b.count === 1 ? "" : "s"} {verb}
        </div>
      ))}

      <div className="font-mono text-xs text-pink-400/80 pl-4 pt-1 space-y-0.5">
        {buckets.slice(0, 3).flatMap(b => b.samples.map(s => (
          <div key={s} className="truncate">{s}</div>
        )))}
      </div>

      {rollups.length > 0 && (
        <div className="font-mono text-xs text-slate-400 pl-1 pt-1.5 space-y-0.5">
          {rollups.map(r => (
            <div key={r.directory}>
              In <span className="text-pink-400">{r.directory}</span>,{" "}
              <b className="text-white">{r.count}</b> files {verb}
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
export function GroupedChangesView({ changes }: { changes: ReportChangeDetail[] }) {
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
              </div>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}
