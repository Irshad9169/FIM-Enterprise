import { Link, Outlet } from "react-router-dom";
import { LayoutDashboard, FileText, Clock, ShieldCheck, LogOut } from "lucide-react";
export default function Layout() {
  const handleLogout = () => { localStorage.removeItem("fim_token"); window.location.href = "/api/v1/sso/login"; };
  return (
    <div className="flex h-screen bg-slate-950 text-slate-200">
      <aside className="w-64 bg-slate-900 border-r border-slate-800 flex flex-col">
        <div className="p-6 text-xl font-bold text-white">FIM Enterprise</div>
        <nav className="flex-1 p-4 space-y-2">
          <Link to="/" className="flex items-center gap-3 p-2 hover:bg-slate-800 rounded-lg"><LayoutDashboard size={18}/> Dashboard</Link>
          <Link to="/reports" className="flex items-center gap-3 p-2 hover:bg-slate-800 rounded-lg"><FileText size={18}/> Reports</Link>
          <Link to="/scans" className="flex items-center gap-3 p-2 hover:bg-slate-800 rounded-lg"><Clock size={18}/> Scans</Link>
          <Link to="/baselines" className="flex items-center gap-3 p-2 hover:bg-slate-800 rounded-lg"><ShieldCheck size={18}/> Baselines</Link>
        </nav>
        <button onClick={handleLogout} className="p-4 text-red-400 flex items-center gap-3 hover:bg-red-900/10"><LogOut size={18}/> Logout</button>
      </aside>
      <main className="flex-1 overflow-auto p-8"><Outlet /></main>
    </div>
  );
}
