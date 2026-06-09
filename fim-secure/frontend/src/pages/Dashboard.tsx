import { Shield } from "lucide-react";
export default function Dashboard() {
  return (
    <div className="space-y-6">
      <h1 className="text-2xl font-bold text-white">System Overview</h1>
      <div className="bg-slate-900 p-12 rounded-xl border border-slate-800 text-center">
        <Shield size={48} className="mx-auto text-slate-700 mb-4" />
        <p className="text-slate-400">Welcome to FIM Enterprise. Select a report from the sidebar.</p>
      </div>
    </div>
  );
}
