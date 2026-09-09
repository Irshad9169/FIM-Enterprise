import { useState } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { fetchSessions, revokeSession, revokeAllUserSessions } from "../api/dashboard";
import { formatServerDateTime } from "../lib/formatDate";
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

  if (isLoading) return <div className="text-center py-12 text-muted-foreground">Loading sessions...</div>;

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
      <div className="bg-card p-4 rounded-lg border border-border flex justify-between items-center">
        <div>
          <h1 className="text-xl font-bold text-foreground flex items-center gap-2"><Shield size={20} className="text-sky-400" /> Active Sessions</h1>
          <p className="text-muted-foreground text-sm">{sessions.length} active session(s)</p>
        </div>
      </div>

      {Object.entries(byUser).map(([username, userSessions]) => (
        <div key={username} className="bg-card border border-border rounded-lg overflow-hidden">
          <div className="px-5 py-3 border-b border-border flex justify-between items-center">
            <div className="flex items-center gap-2">
              <Monitor size={14} className="text-sky-400" />
              <span className="text-foreground font-medium text-sm">{username}</span>
              <span className="text-muted-foreground text-xs">({userSessions.length} session{userSessions.length > 1 ? "s" : ""})</span>
            </div>
            {userSessions.length > 1 && (
              <button onClick={() => handleRevokeAll(userSessions[0].user_id, username)}
                className="px-3 py-1 bg-red-600/20 text-red-400 text-xs rounded border border-red-800 hover:bg-red-600/40 flex items-center gap-1">
                <LogOut size={12} /> Revoke All
              </button>
            )}
          </div>
          <table className="w-full text-sm">
            <thead className="text-muted-foreground text-xs bg-background/40">
              <tr>
                <th className="px-5 py-2 text-left">IP Address</th>
                <th className="px-5 py-2 text-left">Browser/Agent</th>
                <th className="px-5 py-2 text-left">Login Time</th>
                <th className="px-5 py-2 text-left">Last Active</th>
                <th className="px-5 py-2 text-left">Expires</th>
                <th className="px-5 py-2 text-center">Action</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-border">
              {userSessions.map((s: any) => (
                <tr key={s.id} className="hover:bg-muted/50">
                  <td className="px-5 py-2.5 font-mono text-xs text-foreground/90">{s.ip_address || "-"}</td>
                  <td className="px-5 py-2.5 text-xs text-muted-foreground truncate max-w-xs">{s.user_agent?.split(" ").slice(0, 3).join(" ") || "-"}</td>
                  <td className="px-5 py-2.5 text-xs text-muted-foreground">{formatServerDateTime(s.created_at)}</td>
                  <td className="px-5 py-2.5 text-xs text-muted-foreground">{formatServerDateTime(s.last_activity)}</td>
                  <td className="px-5 py-2.5 text-xs text-muted-foreground">{formatServerDateTime(s.expires_at)}</td>
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
        <div className="text-center py-12 text-muted-foreground">No active sessions</div>
      )}
    </div>
  );
}
