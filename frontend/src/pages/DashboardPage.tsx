import { useQuery } from "@tanstack/react-query";
import { useNavigate } from "react-router-dom";
import {
  fetchDashboardStats, fetchAlertStats, fetchHealthSummary, fetchTrends,
  fetchBaselines, fetchScans
} from "../api/dashboard";
import {
  ShieldAlert, Activity, Server, FileText, CheckCircle, Clock, TrendingUp,
  FileCheck, Scan
} from "lucide-react";
import {
  AreaChart, Area, BarChart, Bar, PieChart, Pie, Cell,
  XAxis, YAxis, CartesianGrid, Tooltip, ResponsiveContainer, Legend
} from "recharts";

const fetchReportStats = async () => {
  const token = localStorage.getItem("fim_token");
  const res = await fetch("/api/v1/dashboard/reports/stats", {
    headers: { Authorization: `Bearer ${token}` }
  });
  return res.json();
};

const SEVERITY_COLORS: Record<string, string> = {
  critical: "#ef4444", high: "#f97316", medium: "#eab308", low: "#3b82f6"
};
const STATUS_COLORS: Record<string, string> = {
  open: "#f97316", acknowledged: "#38bdf8", investigating: "#a78bfa",
  resolved: "#22c55e", false_positive: "#64748b"
};

export default function DashboardPage() {
  const navigate = useNavigate();
  const { data: stats } = useQuery({ queryKey: ["dashboardStats"], queryFn: fetchDashboardStats });
  const { data: alertStats } = useQuery({ queryKey: ["alertStats"], queryFn: fetchAlertStats });
  const { data: health } = useQuery({ queryKey: ["healthSummary"], queryFn: fetchHealthSummary });
  const { data: reportStats } = useQuery({ queryKey: ["reportStats"], queryFn: fetchReportStats });
  const { data: trends } = useQuery({ queryKey: ["trends"], queryFn: () => fetchTrends(30), refetchInterval: 60000 });

  // Shares a cache key with the sidebar's own queries (DashboardLayout.tsx),
  // so react-query dedupes these — no extra network round trip just because
  // both are mounted at once.
  const { data: baselinesData } = useQuery({ queryKey: ["baselines"], queryFn: fetchBaselines, refetchInterval: 60_000 });
  const pendingBaselines = (baselinesData?.baselines || []).filter((b: any) =>
    !["approved", "integrity_failed", "superseded", "replaced"].includes(b.status)
  ).length;

  const { data: scansSummaryData } = useQuery({ queryKey: ["scans-summary"], queryFn: fetchScans, refetchInterval: 60_000 });
  const scanSummary = scansSummaryData?.summary || {};
  const staleScans = (scanSummary.stale || 0) + (scanSummary.warning || 0) +
    (scanSummary.critical || 0) + (scanSummary.never_scanned || 0);

  // Format day labels for charts
  const alertTrend = (trends?.alerts_by_day || []).map((d: any) => ({
    ...d, label: d.day.slice(5) // "MM-DD"
  }));
  const scanTrend = (trends?.scans_by_day || []).map((d: any) => ({
    ...d, label: d.day.slice(5)
  }));
  const sevDist = trends?.severity_distribution || [];
  const statusDist = trends?.status_distribution || [];

  return (
    <div className="space-y-6">
      {/* Needs Attention — only visually "loud" (pulsing) when count > 0;
          shown at 0 too, styled neutrally, so "nothing pending" is still
          visible reassurance rather than the section just disappearing. */}
      <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
        <AttentionCard
          label="Pending Baseline Approvals" value={pendingBaselines}
          icon={<FileCheck size={24} />} color="yellow" onClick={() => navigate('/baselines')}
        />
        <AttentionCard
          label="Stale Scans" value={staleScans}
          icon={<Scan size={24} />} color="red" onClick={() => navigate('/scans')}
        />
      </div>

      {/* Overview Cards */}
      <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-6">
        <StatCard label="Total Alerts" value={stats?.alerts.total || 0}
          icon={<ShieldAlert className="text-red-500" size={24} />} onClick={() => navigate('/alerts')} />
        <StatCard label="Open Alerts" value={stats?.alerts.open || 0}
          icon={<Activity className="text-orange-500" size={24} />} onClick={() => navigate('/alerts')} />
        <StatCard label="Online Agents" value={stats?.agents.online || 0}
          icon={<Server className="text-green-500" size={24} />} onClick={() => navigate('/agents')} />
        <div onClick={() => navigate('/reports')}
          className="bg-slate-900 p-6 rounded-lg border border-slate-800 cursor-pointer hover:border-sky-600 transition-colors">
          <div className="flex justify-between items-start">
            <div>
              <p className="text-slate-400 text-sm font-medium">Pending Reports</p>
              <h3 className="text-3xl font-bold text-white mt-2">{reportStats?.pending_review || 0}</h3>
            </div>
            <div className="p-2 bg-yellow-900/30 rounded-lg"><FileText className="text-yellow-500" size={24} /></div>
          </div>
          <div className="mt-4 flex items-center gap-2 text-sm">
            <span className="text-red-400 font-medium">{reportStats?.missing_reports || 0}</span>
            <span className="text-slate-500">missing last 7 days</span>
          </div>
        </div>
      </div>

      {/* Charts Row 1: Alert Trend + Severity Donut */}
      <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
        <div className="lg:col-span-2 bg-slate-900 p-6 rounded-lg border border-slate-800">
          <h3 className="text-lg font-semibold mb-4 text-white flex items-center gap-2">
            <TrendingUp size={18} className="text-sky-400" /> Alerts Trend (30 Days)
          </h3>
          {alertTrend.length > 0 ? (
            <ResponsiveContainer width="100%" height={250}>
              <AreaChart data={alertTrend}>
                <defs>
                  <linearGradient id="alertGrad" x1="0" y1="0" x2="0" y2="1">
                    <stop offset="5%" stopColor="#f97316" stopOpacity={0.3} />
                    <stop offset="95%" stopColor="#f97316" stopOpacity={0} />
                  </linearGradient>
                </defs>
                <CartesianGrid strokeDasharray="3 3" stroke="#334155" />
                <XAxis dataKey="label" stroke="#64748b" fontSize={11} />
                <YAxis stroke="#64748b" fontSize={11} allowDecimals={false} />
                <Tooltip
                  contentStyle={{ backgroundColor: '#1e293b', border: '1px solid #334155', borderRadius: 8, fontSize: 12 }}
                  labelStyle={{ color: '#94a3b8' }}
                />
                <Area type="monotone" dataKey="total" stroke="#f97316" fill="url(#alertGrad)" strokeWidth={2} name="Total" />
                <Area type="monotone" dataKey="critical" stroke="#ef4444" fill="none" strokeWidth={1.5} strokeDasharray="4 2" name="Critical" />
                <Area type="monotone" dataKey="high" stroke="#fb923c" fill="none" strokeWidth={1.5} strokeDasharray="4 2" name="High" />
                <Legend wrapperStyle={{ fontSize: 11 }} />
              </AreaChart>
            </ResponsiveContainer>
          ) : (
            <div className="h-[250px] flex items-center justify-center text-slate-500 text-sm">No alert data yet</div>
          )}
        </div>

        {/* Severity + Status Donuts */}
        <div className="bg-slate-900 p-6 rounded-lg border border-slate-800 space-y-6">
          <div>
            <h3 className="text-sm font-semibold mb-3 text-white">Open Alerts by Severity</h3>
            {sevDist.length > 0 ? (
              <ResponsiveContainer width="100%" height={130}>
                <PieChart>
                  <Pie data={sevDist} dataKey="value" nameKey="name" cx="50%" cy="50%"
                    innerRadius={35} outerRadius={55} paddingAngle={3}>
                    {sevDist.map((e: any, i: number) => (
                      <Cell key={i} fill={SEVERITY_COLORS[e.name] || "#64748b"} />
                    ))}
                  </Pie>
                  <Tooltip contentStyle={{ backgroundColor: '#1e293b', border: '1px solid #334155', borderRadius: 8, fontSize: 12 }} />
                </PieChart>
              </ResponsiveContainer>
            ) : (
              <div className="h-[130px] flex items-center justify-center text-slate-500 text-sm">No open alerts</div>
            )}
            <div className="flex flex-wrap justify-center gap-3 mt-1">
              {sevDist.map((s: any) => (
                <div key={s.name} className="flex items-center gap-1 text-xs">
                  <div className="w-2 h-2 rounded-full" style={{ backgroundColor: SEVERITY_COLORS[s.name] || '#64748b' }} />
                  <span className="text-slate-400 capitalize">{s.name}</span>
                  <span className="text-white font-bold">{s.value}</span>
                </div>
              ))}
            </div>
          </div>

          <div>
            <h3 className="text-sm font-semibold mb-3 text-white">All Alerts by Status</h3>
            {statusDist.length > 0 ? (
              <ResponsiveContainer width="100%" height={130}>
                <PieChart>
                  <Pie data={statusDist} dataKey="value" nameKey="name" cx="50%" cy="50%"
                    innerRadius={35} outerRadius={55} paddingAngle={3}>
                    {statusDist.map((e: any, i: number) => (
                      <Cell key={i} fill={STATUS_COLORS[e.name] || "#64748b"} />
                    ))}
                  </Pie>
                  <Tooltip contentStyle={{ backgroundColor: '#1e293b', border: '1px solid #334155', borderRadius: 8, fontSize: 12 }} />
                </PieChart>
              </ResponsiveContainer>
            ) : (
              <div className="h-[130px] flex items-center justify-center text-slate-500 text-sm">No data</div>
            )}
            <div className="flex flex-wrap justify-center gap-3 mt-1">
              {statusDist.map((s: any) => (
                <div key={s.name} className="flex items-center gap-1 text-xs">
                  <div className="w-2 h-2 rounded-full" style={{ backgroundColor: STATUS_COLORS[s.name] || '#64748b' }} />
                  <span className="text-slate-400 capitalize">{s.name}</span>
                  <span className="text-white font-bold">{s.value}</span>
                </div>
              ))}
            </div>
          </div>
        </div>
      </div>

      {/* Charts Row 2: Scans + Severity Cards + Agent Health */}
      <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
        {/* Scan Activity */}
        <div className="lg:col-span-1 bg-slate-900 p-6 rounded-lg border border-slate-800">
          <h3 className="text-lg font-semibold mb-4 text-white">Scan Activity</h3>
          {scanTrend.length > 0 ? (
            <ResponsiveContainer width="100%" height={200}>
              <BarChart data={scanTrend}>
                <CartesianGrid strokeDasharray="3 3" stroke="#334155" />
                <XAxis dataKey="label" stroke="#64748b" fontSize={10} />
                <YAxis stroke="#64748b" fontSize={10} allowDecimals={false} />
                <Tooltip contentStyle={{ backgroundColor: '#1e293b', border: '1px solid #334155', borderRadius: 8, fontSize: 12 }} />
                <Bar dataKey="scans" fill="#38bdf8" radius={[3, 3, 0, 0]} name="Scans" />
                <Bar dataKey="changes" fill="#f97316" radius={[3, 3, 0, 0]} name="Changes" />
                <Legend wrapperStyle={{ fontSize: 11 }} />
              </BarChart>
            </ResponsiveContainer>
          ) : (
            <div className="h-[200px] flex items-center justify-center text-slate-500 text-sm">No scan data</div>
          )}
        </div>

        {/* Alerts by Severity (existing cards) */}
        <div className="bg-slate-900 p-6 rounded-lg border border-slate-800">
          <h3 className="text-lg font-semibold mb-4 text-white">Alerts by Severity</h3>
          <div className="grid grid-cols-2 gap-4">
            <SeverityCard label="Critical" value={alertStats?.by_severity.critical || 0} color="red" />
            <SeverityCard label="High" value={alertStats?.by_severity.high || 0} color="orange" />
            <SeverityCard label="Medium" value={alertStats?.by_severity.medium || 0} color="yellow" />
            <SeverityCard label="Low" value={alertStats?.by_severity.low || 0} color="blue" />
          </div>
        </div>

        {/* Agent Health (existing cards) */}
        <div className="bg-slate-900 p-6 rounded-lg border border-slate-800">
          <h3 className="text-lg font-semibold mb-4 text-white">Agent Health</h3>
          <div className="grid grid-cols-2 gap-4">
            <HealthCard label="Healthy" value={health?.healthy_agents || 0} icon={<CheckCircle size={20} />} color="text-green-500" />
            <HealthCard label="Unhealthy" value={health?.unhealthy_agents || 0} icon={<Activity size={20} />} color="text-red-500" />
            <HealthCard label="Stale" value={health?.stale_agents || 0} icon={<Clock size={20} />} color="text-slate-500" />
            <HealthCard label="Total" value={health?.total_agents || 0} icon={<Server size={20} />} color="text-blue-500" />
          </div>
        </div>
      </div>
    </div>
  );
}

function AttentionCard({ label, value, icon, color, onClick }: any) {
  const active = value > 0;
  const theme: Record<string, { border: string; iconBg: string; icon: string; value: string }> = {
    yellow: { border: "border-yellow-700/60", iconBg: "bg-yellow-900/30", icon: "text-yellow-500", value: "text-yellow-400" },
    red:    { border: "border-red-700/60",    iconBg: "bg-red-900/30",    icon: "text-red-500",    value: "text-red-400" },
  };
  const t = theme[color];
  return (
    <div onClick={onClick}
      className={`bg-slate-900 p-6 rounded-lg border cursor-pointer transition-colors hover:border-sky-600 ${
        active ? `${t.border} border-l-4` : "border-slate-800"
      }`}>
      <div className="flex justify-between items-start">
        <div>
          <p className="text-slate-400 text-sm font-medium">{label}</p>
          <h3 className={`text-3xl font-bold mt-2 ${active ? t.value : "text-white"}`}>{value}</h3>
        </div>
        <div className={`p-2 rounded-lg ${active ? `${t.iconBg} fim-attn-pulse` : "bg-slate-800"}`}>
          <span className={active ? t.icon : "text-slate-500"}>{icon}</span>
        </div>
      </div>
    </div>
  );
}

function StatCard({ label, value, icon, onClick }: any) {
  return (
    <div onClick={onClick}
      className="bg-slate-900 p-6 rounded-lg border border-slate-800 cursor-pointer hover:border-sky-600 transition-colors">
      <div className="flex justify-between items-start">
        <div>
          <p className="text-slate-400 text-sm font-medium">{label}</p>
          <h3 className="text-3xl font-bold text-white mt-2">{value}</h3>
        </div>
        <div className="p-2 bg-slate-800 rounded-lg">{icon}</div>
      </div>
    </div>
  );
}

function SeverityCard({ label, value, color }: any) {
  const colors: any = {
    red: "bg-red-900/20 text-red-500 border-red-900",
    orange: "bg-orange-900/20 text-orange-500 border-orange-900",
    yellow: "bg-yellow-900/20 text-yellow-500 border-yellow-900",
    blue: "bg-blue-900/20 text-blue-500 border-blue-900",
  };
  return (
    <div className={`p-4 rounded border ${colors[color]}`}>
      <div className="text-sm font-medium opacity-80">{label}</div>
      <div className="text-2xl font-bold mt-1">{value}</div>
    </div>
  );
}

function HealthCard({ label, value, icon, color }: any) {
  return (
    <div className="flex items-center justify-between p-4 bg-slate-800/50 rounded border border-slate-700">
      <div className="flex items-center gap-3">
        <span className={color}>{icon}</span>
        <span className="text-slate-300 font-medium">{label}</span>
      </div>
      <span className="text-xl font-bold text-white">{value}</span>
    </div>
  );
}
