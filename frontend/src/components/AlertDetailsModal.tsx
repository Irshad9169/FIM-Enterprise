import { useState } from "react";
import { acknowledgeAlert } from "../api/dashboard";

interface AlertDetailsModalProps {
  alert: any;
  onClose: () => void;
  onUpdate?: () => void;
}

export default function AlertDetailsModal({ alert, onClose, onUpdate }: AlertDetailsModalProps) {
  const [activeTab, setActiveTab] = useState<"details" | "diff">("details");
  const [acking, setAcking] = useState(false);
  const [ackError, setAckError] = useState("");
  const [currentStatus, setCurrentStatus] = useState(alert.status);

  const handleAcknowledge = async () => {
    setAcking(true);
    setAckError("");
    try {
      await acknowledgeAlert(alert.id);
      setCurrentStatus("acknowledged");
      if (onUpdate) onUpdate();
    } catch (e: any) {
      setAckError(e.message || "Failed to acknowledge");
    } finally {
      setAcking(false);
    }
  };

  const renderDiff = () => {
    const prev = alert.previous_state || {};
    const curr = alert.current_state || {};

    return (
      <div className="space-y-3">
        <div className="grid grid-cols-2 gap-4">
          <div>
            <div className="text-xs font-semibold text-slate-400 mb-2">Previous State</div>
            <div className="bg-slate-950 rounded p-3 text-xs font-mono">
              {prev.hash && <div className="mb-1"><span className="text-slate-500">Hash:</span> {prev.hash}</div>}
              {prev.size !== undefined && <div className="mb-1"><span className="text-slate-500">Size:</span> {prev.size} bytes</div>}
              {prev.permissions && <div className="mb-1"><span className="text-slate-500">Perms:</span> {prev.permissions}</div>}
              {prev.owner !== undefined && <div className="mb-1"><span className="text-slate-500">Owner:</span> {prev.owner}</div>}
              {prev.modified_time && <div className="mb-1"><span className="text-slate-500">Modified:</span> {prev.modified_time}</div>}
              {Object.keys(prev).length === 0 && <div className="text-slate-600">File did not exist</div>}
            </div>
          </div>

          <div>
            <div className="text-xs font-semibold text-slate-400 mb-2">Current State</div>
            <div className="bg-slate-950 rounded p-3 text-xs font-mono">
              {curr.hash && <div className="mb-1"><span className="text-slate-500">Hash:</span> {curr.hash}</div>}
              {curr.size !== undefined && <div className="mb-1"><span className="text-slate-500">Size:</span> {curr.size} bytes</div>}
              {curr.permissions && <div className="mb-1"><span className="text-slate-500">Perms:</span> {curr.permissions}</div>}
              {curr.owner !== undefined && <div className="mb-1"><span className="text-slate-500">Owner:</span> {curr.owner}</div>}
              {curr.modified_time && <div className="mb-1"><span className="text-slate-500">Modified:</span> {curr.modified_time}</div>}
              {Object.keys(curr).length === 0 && <div className="text-slate-600">File deleted</div>}
            </div>
          </div>
        </div>

        {alert.change_details && (
          <div>
            <div className="text-xs font-semibold text-slate-400 mb-2">Changes Detected</div>
            <div className="bg-slate-950 rounded p-3">
              <ul className="text-xs space-y-1">
                {alert.change_details.hash_changed && (
                  <li className="text-orange-400">🔸 File content modified</li>
                )}
                {alert.change_details.size_changed && (
                  <li className="text-yellow-400">🔸 File size changed: {alert.change_details.size_diff}</li>
                )}
                {alert.change_details.permissions_changed && (
                  <li className="text-red-400">🔸 Permissions changed: {alert.change_details.old_perms} → {alert.change_details.new_perms}</li>
                )}
                {alert.change_details.owner_changed && (
                  <li className="text-red-400">🔸 Owner changed</li>
                )}
              </ul>
            </div>
          </div>
        )}
      </div>
    );
  };

  return (
    <div className="fixed inset-0 bg-black/80 flex items-center justify-center z-50" onClick={onClose}>
      <div
        className="bg-slate-900 border border-slate-700 rounded-lg w-full max-w-4xl max-h-[90vh] overflow-hidden flex flex-col"
        onClick={(e) => e.stopPropagation()}
      >
        {/* Header */}
        <div className="border-b border-slate-800 px-6 py-4 flex items-center justify-between">
          <div>
            <h2 className="text-lg font-semibold">Alert Details</h2>
            <div className="text-xs text-slate-400 mt-1">ID: {alert.id.slice(0, 8)}...</div>
          </div>
          <button
            onClick={onClose}
            className="text-slate-400 hover:text-white text-2xl leading-none"
          >
            ×
          </button>
        </div>

        {/* Tabs */}
        <div className="border-b border-slate-800 px-6">
          <div className="flex gap-4">
            <button
              onClick={() => setActiveTab("details")}
              className={`px-3 py-2 text-sm font-medium border-b-2 transition-colors ${
                activeTab === "details"
                  ? "border-sky-500 text-sky-400"
                  : "border-transparent text-slate-400 hover:text-slate-200"
              }`}
            >
              Details
            </button>
            <button
              onClick={() => setActiveTab("diff")}
              className={`px-3 py-2 text-sm font-medium border-b-2 transition-colors ${
                activeTab === "diff"
                  ? "border-sky-500 text-sky-400"
                  : "border-transparent text-slate-400 hover:text-slate-200"
              }`}
            >
              File Diff
            </button>
          </div>
        </div>

        {/* Content */}
        <div className="flex-1 overflow-y-auto p-6">
          {activeTab === "details" ? (
            <div className="space-y-4">
              <div className="grid grid-cols-2 gap-4">
                <div>
                  <div className="text-xs text-slate-500 mb-1">File Path</div>
                  <div className="text-sm font-mono bg-slate-950 px-3 py-2 rounded">
                    {alert.file_path}
                  </div>
                </div>
                <div>
                  <div className="text-xs text-slate-500 mb-1">Agent</div>
                  <div className="text-sm bg-slate-950 px-3 py-2 rounded">
                    {alert.agent_hostname}
                  </div>
                </div>
              </div>

              <div className="grid grid-cols-3 gap-4">
                <div>
                  <div className="text-xs text-slate-500 mb-1">Severity</div>
                  <span
                    className={`inline-block px-3 py-1 rounded-full text-xs font-medium ${
                      alert.severity === "critical"
                        ? "bg-red-900/40 text-red-300 border border-red-700"
                        : alert.severity === "high"
                        ? "bg-orange-900/40 text-orange-300 border border-orange-700"
                        : "bg-slate-800 text-slate-200 border border-slate-600"
                    }`}
                  >
                    {alert.severity}
                  </span>
                </div>
                <div>
                  <div className="text-xs text-slate-500 mb-1">Status</div>
                  <span className={`inline-block px-3 py-1 rounded-full text-xs font-medium ${
                    currentStatus === "acknowledged"
                      ? "bg-sky-900/40 text-sky-300 border border-sky-700"
                      : "bg-slate-800 border border-slate-600"
                  }`}>
                    {currentStatus}
                  </span>
                </div>
                <div>
                  <div className="text-xs text-slate-500 mb-1">Type</div>
                  <span className="inline-block px-3 py-1 rounded-full text-xs font-medium bg-slate-800 border border-slate-600">
                    {alert.alert_type}
                  </span>
                </div>
              </div>

              <div>
                <div className="text-xs text-slate-500 mb-1">Detected At</div>
                <div className="text-sm bg-slate-950 px-3 py-2 rounded">
                  {alert.detected_at ? new Date(alert.detected_at).toLocaleString() : "N/A"}
                </div>
              </div>
            </div>
          ) : (
            renderDiff()
          )}
        </div>

        {/* Footer */}
        <div className="border-t border-slate-800 px-6 py-4 flex justify-between items-center">
          {ackError && (
            <div className="text-red-400 text-xs">{ackError}</div>
          )}
          {currentStatus === "acknowledged" && !ackError && (
            <div className="text-sky-400 text-xs flex items-center gap-1">
              ✓ Alert acknowledged
            </div>
          )}
          {!ackError && currentStatus !== "acknowledged" && <div />}
          <div className="flex gap-3">
            <button
              onClick={onClose}
              className="px-4 py-2 rounded bg-slate-800 hover:bg-slate-700 text-sm"
            >
              Close
            </button>
            {currentStatus === "open" && (
              <button
                onClick={handleAcknowledge}
                disabled={acking}
                className="px-4 py-2 rounded bg-sky-600 hover:bg-sky-500 text-sm font-medium disabled:opacity-50 flex items-center gap-2"
              >
                {acking ? "Acknowledging…" : "Acknowledge"}
              </button>
            )}
          </div>
        </div>
      </div>
    </div>
  );
}
