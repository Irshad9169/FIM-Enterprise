import { useState } from "react";
import { HostWithChanges } from "../api/dashboard";

interface Props {
  hosts: HostWithChanges[];
  commonDomain?: string;
}

export default function HostListTable({ hosts, commonDomain }: Props) {
  const [showAll, setShowAll] = useState(false);
  const [expandedHost, setExpandedHost] = useState<string | null>(null);
  const displayHosts = showAll ? hosts : hosts.slice(0, 10);

  const getSeverityColor = (severity: string) => {
    switch (severity) {
      case "critical":
        return "text-red-400";
      case "high":
        return "text-orange-400";
      case "medium":
        return "text-yellow-400";
      default:
        return "text-muted-foreground";
    }
  };

  const copyHostnames = () => {
    const hostnames = hosts.map((h) => h.hostname).join("\n");
    navigator.clipboard.writeText(hostnames);
    alert(`Copied ${hosts.length} hostnames to clipboard!`);
  };

  const formatHash = (hash: string | null) => {
    if (!hash) return "-";
    return hash.substring(0, 12) + "...";
  };

  return (
    <div className="space-y-2">
      <div className="flex items-center justify-between text-xs">
        <span className="text-muted-foreground font-semibold">
          🖥️ Affected Hosts ({hosts.length})
          {commonDomain && (
            <span className="ml-2 text-muted-foreground">· {commonDomain}</span>
          )}
        </span>
        <button
          onClick={copyHostnames}
          className="text-sky-400 hover:text-sky-300"
        >
          📋 Copy All
        </button>
      </div>

      <div className="bg-background rounded-lg border border-border overflow-hidden">
        <table className="min-w-full text-xs">
          <thead className="bg-card text-muted-foreground">
            <tr>
              <th className="px-3 py-2 text-left">Hostname</th>
              <th className="px-3 py-2 text-left">Change Type</th>
              <th className="px-3 py-2 text-center">Severity</th>
              <th className="px-3 py-2 text-left">File Hash (Old → New)</th>
              <th className="px-3 py-2 text-left">Detected</th>
              <th className="px-3 py-2"></th>
            </tr>
          </thead>
          <tbody>
            {displayHosts.map((host) => (
              <>
                <tr
                  key={host.alert_id}
                  className="border-t border-border hover:bg-card/50"
                >
                  <td className="px-3 py-2 font-mono text-foreground">
                    {host.hostname}
                  </td>
                  <td className="px-3 py-2 text-foreground/90">
                    {host.alert_type}
                  </td>
                  <td className="px-3 py-2 text-center">
                    <span className={getSeverityColor(host.severity)}>
                      {host.severity}
                    </span>
                  </td>
                  <td className="px-3 py-2 font-mono text-xs">
                    {host.file_changes.previous_hash && host.file_changes.current_hash ? (
                      <div className="flex items-center gap-1">
                        <span className="text-red-400" title={host.file_changes.previous_hash}>
                          {formatHash(host.file_changes.previous_hash)}
                        </span>
                        <span className="text-muted-foreground">→</span>
                        <span className="text-green-400" title={host.file_changes.current_hash}>
                          {formatHash(host.file_changes.current_hash)}
                        </span>
                      </div>
                    ) : host.file_changes.current_hash ? (
                      <span className="text-green-400">New file</span>
                    ) : (
                      <span className="text-red-400">Deleted</span>
                    )}
                  </td>
                  <td className="px-3 py-2 text-muted-foreground">
                    {new Date(host.detected_at).toLocaleString()}
                  </td>
                  <td className="px-3 py-2">
                    <button
                      onClick={() =>
                        setExpandedHost(
                          expandedHost === host.alert_id ? null : host.alert_id
                        )
                      }
                      className="text-sky-400 hover:text-sky-300"
                    >
                      {expandedHost === host.alert_id ? "▲" : "▼"}
                    </button>
                  </td>
                </tr>
                {expandedHost === host.alert_id && (
                  <tr className="border-t border-border bg-card">
                    <td colSpan={6} className="px-6 py-3">
                      <div className="grid grid-cols-2 gap-4 text-xs">
                        <div>
                          <div className="font-semibold text-muted-foreground mb-2">
                            Previous State
                          </div>
                          <div className="space-y-1 bg-background p-3 rounded">
                            <div>
                              <span className="text-muted-foreground">Hash:</span>{" "}
                              <span className="font-mono text-red-300">
                                {host.file_changes.previous_hash || "N/A"}
                              </span>
                            </div>
                            <div>
                              <span className="text-muted-foreground">Size:</span>{" "}
                              {host.file_changes.previous_size || "N/A"} bytes
                            </div>
                            <div>
                              <span className="text-muted-foreground">Permissions:</span>{" "}
                              {host.file_changes.previous_permissions || "N/A"}
                            </div>
                            <div>
                              <span className="text-muted-foreground">Owner:</span>{" "}
                              {host.file_changes.previous_owner ?? "N/A"}
                            </div>
                          </div>
                        </div>
                        <div>
                          <div className="font-semibold text-muted-foreground mb-2">
                            Current State
                          </div>
                          <div className="space-y-1 bg-background p-3 rounded">
                            <div>
                              <span className="text-muted-foreground">Hash:</span>{" "}
                              <span className="font-mono text-green-300">
                                {host.file_changes.current_hash || "N/A"}
                              </span>
                            </div>
                            <div>
                              <span className="text-muted-foreground">Size:</span>{" "}
                              {host.file_changes.current_size || "N/A"} bytes
                            </div>
                            <div>
                              <span className="text-muted-foreground">Permissions:</span>{" "}
                              {host.file_changes.current_permissions || "N/A"}
                            </div>
                            <div>
                              <span className="text-muted-foreground">Owner:</span>{" "}
                              {host.file_changes.current_owner ?? "N/A"}
                            </div>
                          </div>
                        </div>
                      </div>
                    </td>
                  </tr>
                )}
              </>
            ))}
          </tbody>
        </table>

        {hosts.length > 10 && (
          <div className="bg-card px-3 py-2 text-center border-t border-border">
            <button
              onClick={() => setShowAll(!showAll)}
              className="text-sky-400 hover:text-sky-300 text-xs"
            >
              {showAll ? "▲ Show Less" : `▼ Show All ${hosts.length} Hosts`}
            </button>
          </div>
        )}
      </div>
    </div>
  );
}
