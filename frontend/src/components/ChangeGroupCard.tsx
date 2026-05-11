import { useState } from "react";
import HostListTable from "./HostListTable";
import { ChangeGroup } from "../api/dashboard";

interface Props {
  group: ChangeGroup;
}

export default function ChangeGroupCard({ group }: Props) {
  const [expanded, setExpanded] = useState(false);

  const getSeverityBadge = (severity: string) => {
    const colors = {
      critical: "bg-red-900/40 text-red-300 border-red-700",
      high: "bg-orange-900/40 text-orange-300 border-orange-700",
      medium: "bg-yellow-900/40 text-yellow-300 border-yellow-700",
      low: "bg-slate-800 text-slate-300 border-slate-600",
    };
    return colors[severity as keyof typeof colors] || colors.low;
  };

  const timeRange = group.affected_hosts?.time_range;
  const timeDiff = timeRange
    ? (new Date(timeRange.end).getTime() - new Date(timeRange.start).getTime()) /
      1000 /
      60
    : 0;

  const commonChanges = group.affected_hosts?.common_changes;

  return (
    <div className="bg-slate-900 border border-slate-800 rounded-lg p-4 space-y-3">
      {/* Header */}
      <div className="flex items-start justify-between">
        <div className="flex-1">
          <div className="flex items-center gap-2 mb-1">
            <span
              className={`px-2 py-1 rounded text-xs border ${getSeverityBadge(
                group.severity
              )}`}
            >
              {group.severity.toUpperCase()}
            </span>
            {group.is_known && (
              <span className="px-2 py-1 rounded text-xs bg-green-900/40 text-green-300 border border-green-700">
                ✓ Known
              </span>
            )}
          </div>
          <div className="text-sm font-semibold text-slate-200 font-mono">
            {group.pattern}
          </div>
          <div className="text-xs text-slate-400 mt-1">
            {group.change_count} changes · {group.server_count} servers
          </div>
        </div>

        <button
          onClick={() => setExpanded(!expanded)}
          className="text-sky-400 hover:text-sky-300 text-sm"
        >
          {expanded ? "▲ Hide" : "▼ Details"}
        </button>
      </div>

      {/* Common Changes Summary */}
      {commonChanges && (
        <div className="grid grid-cols-4 gap-2 text-xs">
          {commonChanges.hash_changed > 0 && (
            <div className="bg-orange-950/30 border border-orange-800 rounded px-2 py-1">
              <span className="text-orange-400">🔸 Content:</span>{" "}
              <span className="text-slate-300">{commonChanges.hash_changed}</span>
            </div>
          )}
          {commonChanges.permissions_changed > 0 && (
            <div className="bg-red-950/30 border border-red-800 rounded px-2 py-1">
              <span className="text-red-400">🔸 Perms:</span>{" "}
              <span className="text-slate-300">{commonChanges.permissions_changed}</span>
            </div>
          )}
          {commonChanges.owner_changed > 0 && (
            <div className="bg-red-950/30 border border-red-800 rounded px-2 py-1">
              <span className="text-red-400">🔸 Owner:</span>{" "}
              <span className="text-slate-300">{commonChanges.owner_changed}</span>
            </div>
          )}
          {commonChanges.size_changed > 0 && (
            <div className="bg-yellow-950/30 border border-yellow-800 rounded px-2 py-1">
              <span className="text-yellow-400">🔸 Size:</span>{" "}
              <span className="text-slate-300">{commonChanges.size_changed}</span>
            </div>
          )}
        </div>
      )}

      {/* Stats */}
      <div className="grid grid-cols-3 gap-3 text-xs">
        <div className="bg-slate-950 rounded px-3 py-2">
          <div className="text-slate-500">First Seen</div>
          <div className="text-slate-300">
            {new Date(group.first_seen).toLocaleString()}
          </div>
        </div>
        <div className="bg-slate-950 rounded px-3 py-2">
          <div className="text-slate-500">Last Seen</div>
          <div className="text-slate-300">
            {new Date(group.last_seen).toLocaleString()}
          </div>
        </div>
        <div className="bg-slate-950 rounded px-3 py-2">
          <div className="text-slate-500">Time Window</div>
          <div className="text-slate-300">
            {timeDiff > 0 ? `${timeDiff.toFixed(1)} min` : "Instant"}
          </div>
        </div>
      </div>

      {/* Pattern Analysis */}
      {timeDiff < 5 && group.server_count > 1 && (
        <div className="bg-blue-950/20 border border-blue-800 rounded px-3 py-2 text-xs">
          <span className="text-blue-400">💡 Automated Change Pattern:</span>{" "}
          <span className="text-slate-300">
            {group.server_count} servers affected within {timeDiff.toFixed(1)} minutes
          </span>
        </div>
      )}

      {/* Expanded Details */}
      {expanded && (
        <div className="pt-3 border-t border-slate-800 space-y-3">
          {group.affected_hosts?.hosts && (
            <HostListTable
              hosts={group.affected_hosts.hosts}
              commonDomain={group.affected_hosts.common_domain}
            />
          )}

          {/* Actions */}
          <div className="flex gap-2">
            <button className="px-3 py-1.5 bg-green-600 hover:bg-green-500 rounded text-xs font-medium">
              ✓ Approve All
            </button>
            <button className="px-3 py-1.5 bg-yellow-600 hover:bg-yellow-500 rounded text-xs font-medium">
              📝 Add Notes
            </button>
            <button className="px-3 py-1.5 bg-slate-700 hover:bg-slate-600 rounded text-xs font-medium">
              🔍 Investigate
            </button>
            <button className="px-3 py-1.5 bg-slate-700 hover:bg-slate-600 rounded text-xs font-medium">
              📋 Export Details
            </button>
          </div>
        </div>
      )}
    </div>
  );
}
