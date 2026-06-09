import { useState } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { fetchSessions, revokeSession, revokeAllUserSessions } from "../api/dashboard";
import { Monitor, LogOut, X, Shield } from "lucide-react";

export default function SessionsPage() {
  const qc = useQueryClient();
  const [revoking, setRevoking] = useState<string | null>(null);

  const { data, isLoading } = useQuery({
    queryKey: ["sessions"],
    queryFn: fetchSessions,
    refetchInterval: 15000,
  });

  const handleRevoke = async (sessionId: string) => {
    setRevoking(sessionId);
    try {
      await revokeSession(sessionId);
      qc.invalidateQueries({ queryKey: ["sessions"] });
    } catch (e: any) {
      alert("Error: " + e.message);
    } finally { setRevoking(null); }
  };

  const handleRevokeAll = async (userId: string, username: string) => {
    if (!confirm(`Revoke ALL sessions for ${username}? They will be logged out immediately.`)) return;
    try {
      await revokeAllUserSessions(userId);
      qc.invalidateQueries({ queryKey: ["sessions"] });
    } catch (e: any) {
      alert("Error: " + e.message);
    }
  };

  if (isLoading) return <div className="text-center py-12 text-slate-400">Loading sessions...</div>;

  const sessions = data?.sessions || [];

  // Group by user
  const byUser: Record<string, any[]> = {};
  for (const s of sessions) {
    const key = s.username || "unknown";
    if (!byUser[key]) byUser[key] = [];
    byUser[key].push(s);
  }

  return (
    <div className="space-y-6">
      <div className="bg-slate-900 p-4 rounded-lg border border-slate-800 flex justify-between items-center">
        <div>
          <h1 className="text-xl font-bold text-white flex items-center gap-2"><Shield size={20} className="text-sky-400" /> Active Sessions</h1>
          <p className="text-slate-400 text-sm">{sessions.length} active session(s)</p>
        </div>
      </div>

      {Object.entries(byUser).map(([username, userSessions]) => (
        <div key={username} className="bg-slate-900 border border-slate-800 rounded-lg overflow-hidden">
          <div className="px-5 py-3 border-b border-slate-800 flex justify-between items-center">
            <div className="flex items-center gap-2">
              <Monitor size={14} className="text-sky-400" />
              <span className="text-white font-medium text-sm">{username}</span>
              <span className="text-slate-500 text-xs">({userSessions.length} session{userSessions.length > 1 ? "s" : ""})</span>
            </div>
            {userSessions.length > 1 && (
              <button onClick={() => handleRevokeAll(userSessions[0].user_id, username)}
                className="px-3 py-1 bg-red-600/20 text-red-400 text-xs rounded border border-red-800 hover:bg-red-600/40 flex items-center gap-1">
                <LogOut size={12} /> Revoke All
              </button>
            )}
          </div>
          <table className="w-full text-sm">
            <thead className="text-slate-500 text-xs bg-slate-950/40">
              <tr>
                <th className="px-5 py-2 text-left">IP Address</th>
                <th className="px-5 py-2 text-left">Browser/Agent</th>
                <th className="px-5 py-2 text-left">Login Time</th>
                <th className="px-5 py-2 text-left">Last Active</th>
                <th className="px-5 py-2 text-left">Expires</th>
                <th className="px-5 py-2 text-center">Action</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-slate-800">
              {userSessions.map((s: any) => (
                <tr key={s.id} className="hover:bg-slate-800/50">
                  <td className="px-5 py-2.5 font-mono text-xs text-slate-300">{s.ip_address || "-"}</td>
                  <td className="px-5 py-2.5 text-xs text-slate-400 truncate max-w-xs">{s.user_agent?.split(" ").slice(0, 3).join(" ") || "-"}</td>
                  <td className="px-5 py-2.5 text-xs text-slate-400">{s.created_at ? new Date(s.created_at).toLocaleString() : "-"}</td>
                  <td className="px-5 py-2.5 text-xs text-slate-400">{s.last_activity ? new Date(s.last_activity).toLocaleString() : "-"}</td>
                  <td className="px-5 py-2.5 text-xs text-slate-400">{s.expires_at ? new Date(s.expires_at).toLocaleString() : "-"}</td>
                  <td className="px-5 py-2.5 text-center">
                    <button onClick={() => handleRevoke(s.id)} disabled={revoking === s.id}
                      className="px-2 py-1 bg-red-600 text-white text-xs rounded hover:bg-red-500 disabled:opacity-50 flex items-center gap-1 mx-auto">
                      <X size={12} /> {revoking === s.id ? "..." : "Revoke"}
                    </button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      ))}

      {sessions.length === 0 && (
        <div className="text-center py-12 text-slate-500">No active sessions</div>
      )}
    </div>
  );
}
