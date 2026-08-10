import { useState, useEffect, createContext, useContext } from "react";
import { Outlet, NavLink, useNavigate } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import { logout } from "../api/auth";
import { fetchBaselines, fetchScans, fetchDiskHealth } from "../api/dashboard";
import {
  LayoutDashboard, Server, Bell, FileCheck, Scan, FileText, Shield,
  Users, History, LogOut, ShieldAlert, Sun, Moon, Monitor, HardDrive
} from "lucide-react";

const PENDING_BASELINE_STATUSES_EXCLUDED = ["approved", "integrity_failed", "superseded", "replaced"];

function NavBadge({ count, color }: { count: number; color: string }) {
  if (count <= 0) return null;
  return (
    <span className={`fim-attn-pulse ml-auto text-[10px] font-bold text-slate-950 rounded-full px-1.5 py-0.5 ${color}`}>
      {count}
    </span>
  );
}

export const ThemeContext = createContext<{ dark: boolean; toggle: () => void }>({
  dark: true, toggle: () => {}
});

export function useTheme() { return useContext(ThemeContext); }

export default function DashboardLayout() {
  const navigate = useNavigate();
  const userRaw = localStorage.getItem("fim_user");
  const user = userRaw ? JSON.parse(userRaw) : null;
  const [dark, setDark] = useState(() => {
    const saved = localStorage.getItem("fim_theme");
    return saved ? saved === "dark" : true;
  });

  useEffect(() => {
    localStorage.setItem("fim_theme", dark ? "dark" : "light");
    document.documentElement.classList.toggle("dark", dark);
  }, [dark]);

  const toggle = () => setDark(d => !d);
  const handleLogout = () => { logout(); navigate("/login"); };

  // Ambient attention indicators — visible from any page, not just when an
  // analyst happens to already be on Baselines/Scans. Independent cache keys
  // from the pages themselves (BaselinesPage also uses ["baselines"], which
  // is fine — same data; ScansPage uses ["scans", debouncedSearch], which
  // must NOT be shared since a search term there shouldn't affect this
  // sidebar-wide count).
  const { data: baselinesData } = useQuery({
    queryKey: ["baselines"], queryFn: fetchBaselines, refetchInterval: 60_000,
  });
  const pendingBaselines = (baselinesData?.baselines || []).filter(
    (b: any) => !PENDING_BASELINE_STATUSES_EXCLUDED.includes(b.status)
  ).length;

  const { data: scansData } = useQuery({
    queryKey: ["scans-summary"], queryFn: fetchScans, refetchInterval: 60_000,
  });
  const scanSummary = scansData?.summary || {};
  const staleScans = (scanSummary.stale || 0) + (scanSummary.warning || 0) +
    (scanSummary.critical || 0) + (scanSummary.never_scanned || 0);

  // fim.scans silently grew to 27GB and took the disk to 0 bytes free with
  // nobody watching (see app/api/system.py) -- this badge is the ambient
  // signal that would have caught it before it became an outage.
  const { data: diskHealthData } = useQuery({
    queryKey: ["disk-health"], queryFn: fetchDiskHealth, refetchInterval: 60_000,
  });
  const diskStatus = diskHealthData?.disk?.status || "ok";
  const diskUsedPct = Math.round(diskHealthData?.disk?.used_pct || 0);

  const bg = dark ? "bg-slate-950" : "bg-gray-50";
  const sidebarBg = dark ? "bg-slate-950 border-slate-800" : "bg-white border-gray-200";
  const textPrimary = dark ? "text-white" : "text-gray-900";
  const textSecondary = dark ? "text-slate-400" : "text-gray-500";
  const textMuted = dark ? "text-slate-500" : "text-gray-400";
  const borderColor = dark ? "border-slate-800" : "border-gray-200";

  const navItemClass = ({ isActive }: { isActive: boolean }) =>
    `flex items-center gap-3 px-4 py-2 rounded-md text-sm font-medium transition-colors ${
      isActive
        ? "bg-blue-600 text-white"
        : dark
          ? "text-slate-400 hover:bg-slate-800 hover:text-white"
          : "text-gray-600 hover:bg-gray-100 hover:text-gray-900"
    }`;

  return (
    <ThemeContext.Provider value={{ dark, toggle }}>
      <div className={`h-screen ${bg} ${dark ? "text-slate-100" : "text-gray-900"} overflow-hidden`}>
        <aside className={`fixed top-0 left-0 w-64 h-screen border-r ${sidebarBg} flex flex-col z-30`}>
          <div className={`p-6 border-b ${borderColor} shrink-0 flex items-center justify-between`}>
            <div className={`flex items-center gap-2 font-bold text-xl ${textPrimary}`}>
              <ShieldAlert className="text-blue-500" />
              FIM Enterprise
            </div>
            <button onClick={toggle} className={`p-1.5 rounded-md ${dark ? "hover:bg-slate-800 text-slate-400" : "hover:bg-gray-100 text-gray-500"}`} title={dark ? "Light mode" : "Dark mode"}>
              {dark ? <Sun size={16} /> : <Moon size={16} />}
            </button>
          </div>

          <nav className="flex-1 p-4 space-y-1 overflow-y-auto">
            <div className={`text-xs font-semibold ${textMuted} uppercase tracking-wider mb-2 px-4`}>Main</div>
            <NavLink to="/" end className={navItemClass}><LayoutDashboard size={18} /> Dashboard</NavLink>
            <NavLink to="/agents" className={navItemClass}><Server size={18} /> Agents</NavLink>
            <NavLink to="/alerts" className={navItemClass}><Bell size={18} /> Alerts</NavLink>

            <div className={`text-xs font-semibold ${textMuted} uppercase tracking-wider mt-6 mb-2 px-4`}>Operations</div>
            <NavLink to="/baselines" className={navItemClass}>
              <FileCheck size={18} /> Baselines
              <NavBadge count={pendingBaselines} color="bg-yellow-500" />
            </NavLink>
            <NavLink to="/scans" className={navItemClass}>
              <Scan size={18} /> Scans
              <NavBadge count={staleScans} color="bg-red-500" />
            </NavLink>
            <NavLink to="/reports" className={navItemClass}><FileText size={18} /> Daily Reports</NavLink>
            <NavLink to="/exclusions" className={navItemClass}><Shield size={18} /> Exclusions</NavLink>

            {(user?.role === 'admin' || user?.role === 'auditor') && (
              <>
                <div className={`text-xs font-semibold ${textMuted} uppercase tracking-wider mt-6 mb-2 px-4`}>Administration</div>
                {user?.role === 'admin' && (
                  <NavLink to="/users" className={navItemClass}><Users size={18} /> Users</NavLink>
                )}
                <NavLink to="/audit" className={navItemClass}><History size={18} /> Audit Logs</NavLink>
                <NavLink to="/sessions" className={navItemClass}><Monitor size={18} /> Sessions</NavLink>
                {user?.role === 'admin' && (
                  <NavLink to="/system-health" className={navItemClass}>
                    <HardDrive size={18} /> System Health
                    <NavBadge count={diskStatus !== "ok" ? diskUsedPct : 0}
                      color={diskStatus === "critical" ? "bg-red-500" : "bg-yellow-500"} />
                  </NavLink>
                )}
              </>
            )}
          </nav>

          <div className={`p-4 border-t ${borderColor} shrink-0`}>
            <div className="flex items-center justify-between">
              <div className="text-sm truncate mr-2">
                <div className={`font-medium ${textPrimary} truncate`}>{user?.username || 'User'}</div>
                <div className={`text-xs ${textMuted} truncate`}>{user?.role}</div>
              </div>
              <button onClick={handleLogout} className={`${textSecondary} hover:${textPrimary} p-1`} title="Logout">
                <LogOut size={18} />
              </button>
            </div>
          </div>
        </aside>

        <main className={`ml-64 h-screen overflow-auto ${bg}`}>
          <div className="w-full p-8">
            <Outlet />
          </div>
        </main>
      </div>
    </ThemeContext.Provider>
  );
}
