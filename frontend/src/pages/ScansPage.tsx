import { useState, useEffect } from "react";
import { useQuery } from "@tanstack/react-query";
import { Search, Clock, FileCheck, AlertTriangle } from "lucide-react";

// Move fetch function OUTSIDE component
const fetchScansAPI = async (search: string) => {
  const token = localStorage.getItem("fim_token");
  const query = search ? `?search=${search}` : '';
  const res = await fetch(`/api/v1/scans${query}`, {
    headers: { Authorization: `Bearer ${token}` }
  });
  return res.json();
};

export default function ScansPage() {
  const [search, setSearch] = useState("");
  const [debouncedSearch, setDebouncedSearch] = useState("");

  // Debounce search to prevent API spam and focus loss
  useEffect(() => {
    const timer = setTimeout(() => setDebouncedSearch(search), 500);
    return () => clearTimeout(timer);
  }, [search]);

  const { data, isLoading } = useQuery({
    queryKey: ["scans", debouncedSearch],
    queryFn: () => fetchScansAPI(debouncedSearch),
    placeholderData: (prev) => prev // Keep previous data while fetching
  });

  const scans = data?.scans || [];

  return (
    <div className="space-y-6">
      <div className="flex justify-between items-center bg-slate-900 p-4 rounded-lg border border-slate-800">
        <div>
          <h1 className="text-xl font-bold text-white">Scan History</h1>
          <p className="text-slate-400 text-sm">Latest scan status per agent</p>
        </div>
        <div className="relative">
          <Search size={16} className="absolute left-3 top-2.5 text-slate-500" />
          <input 
            placeholder="Search agents..." 
            className="pl-9 pr-4 py-2 bg-slate-950 border border-slate-700 rounded text-sm text-white w-64 focus:ring-1 focus:ring-blue-500 outline-none"
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            autoFocus
          />
        </div>
      </div>

      <div className="bg-slate-900 border border-slate-800 rounded-lg overflow-hidden">
        <table className="w-full text-sm text-left text-slate-300">
          <thead className="bg-slate-950/50 text-slate-400 font-semibold uppercase text-xs border-b border-slate-800">
            <tr>
              <th className="px-6 py-4">Agent</th>
              <th className="px-6 py-4">Status</th>
              <th className="px-6 py-4">Files Scanned</th>
              <th className="px-6 py-4">Changes</th>
              <th className="px-6 py-4">Last Scan Time</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-slate-800">
            {scans.length > 0 ? scans.map((scan: any) => (
              <tr key={scan.id} className="hover:bg-slate-800/50">
                <td className="px-6 py-4 font-medium text-white">
                  {scan.agent_hostname || scan.agent_id}
                </td>
                <td className="px-6 py-4">
                  <span className={`px-2 py-1 rounded text-xs border uppercase ${
                    scan.status === 'completed' ? 'bg-green-900/30 text-green-400 border-green-800' : 
                    scan.status === 'running' ? 'bg-blue-900/30 text-blue-400 border-blue-800' :
                    'bg-red-900/30 text-red-400 border-red-800'
                  }`}>
                    {scan.status}
                  </span>
                </td>
                <td className="px-6 py-4">
                  <div className="flex items-center gap-2">
                    <FileCheck size={14} className="text-slate-500" />
                    {scan.files_scanned?.toLocaleString() || 0}
                  </div>
                </td>
                <td className="px-6 py-4">
                  {scan.files_changed > 0 ? (
                    <span className="flex items-center gap-2 text-yellow-400 font-bold">
                      <AlertTriangle size={14} /> {scan.files_changed}
                    </span>
                  ) : (
                    <span className="text-slate-500">0</span>
                  )}
                </td>
                <td className="px-6 py-4 text-slate-400 flex items-center gap-2">
                  <Clock size={14} />
                  {scan.started_at ? new Date(scan.started_at).toLocaleString() : '-'}
                </td>
              </tr>
            )) : (
              <tr>
                <td colSpan={5} className="px-6 py-12 text-center text-slate-500">
                  {isLoading ? "Loading..." : "No scans found matching your search."}
                </td>
              </tr>
            )}
          </tbody>
        </table>
      </div>
    </div>
  );
}
