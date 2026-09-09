import { Shield } from "lucide-react";
export default function Dashboard() {
  return (
    <div className="space-y-6">
      <h1 className="text-2xl font-bold text-foreground">System Overview</h1>
      <div className="bg-card p-12 rounded-xl border border-border text-center">
        <Shield size={48} className="mx-auto text-slate-700 mb-4" />
        <p className="text-muted-foreground">Welcome to FIM Enterprise. Select a report from the sidebar.</p>
      </div>
    </div>
  );
}
