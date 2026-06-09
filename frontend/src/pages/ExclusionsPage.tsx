import { useState } from 'react';
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import {
  Plus, Trash2, Globe, Server, Clock,
  CheckCircle, XCircle, ShieldAlert
} from 'lucide-react';

const token = () => localStorage.getItem("fim_token");
const authFetch = (url: string, opts: RequestInit = {}) =>
  fetch(url, { ...opts, headers: { 'Authorization': `Bearer ${token()}`, 'Content-Type': 'application/json', ...(opts.headers || {}) } });

const fetchExclusions = async (scope: string, agentId?: string) => {
  const url = scope === 'agent' && agentId
    ? `/api/v1/exclusions/agents/${agentId}`
    : '/api/v1/exclusions/global';
  return authFetch(url).then(r => r.json());
};

const fetchPending = async () =>
  authFetch('/api/v1/exclusions/pending').then(r => r.json());

const fetchAgents = async () =>
  authFetch('/api/v1/agents').then(r => r.json());

const createExclusion = async (data: any) => {
  // Clean up empty fields
  const cleanData = { ...data };
  if (!cleanData.agent_id) delete cleanData.agent_id;
  
  const url = cleanData.scope === 'agent' && cleanData.agent_id
    ? `/api/v1/exclusions/agents/${cleanData.agent_id}`
    : '/api/v1/exclusions/global';
  const res = await authFetch(url, { method: 'POST', body: JSON.stringify(cleanData) });
  if (!res.ok) { 
    const e = await res.json(); 
    let errMsg = 'Failed to submit exclusion';
    if (typeof e.detail === 'string') {
      errMsg = e.detail;
    } else if (Array.isArray(e.detail)) {
      errMsg = e.detail.map((err: any) => err.msg || JSON.stringify(err)).join('; ');
    }
    throw new Error(errMsg);
  }
  return res.json();
};

const deleteExclusion = async (id: string) => {
  const res = await authFetch(`/api/v1/exclusions/${id}`, { method: 'DELETE' });
  if (!res.ok) throw new Error("Failed to delete");
};

const approveRule = async (id: string) => {
  const res = await authFetch(`/api/v1/exclusions/${id}/approve`, { method: 'POST' });
  if (!res.ok) { const e = await res.json(); throw new Error(typeof e.detail === 'string' ? e.detail : JSON.stringify(e.detail) || 'Failed'); }
  return res.json();
};

const rejectRule = async ({ id, reason }: { id: string; reason: string }) => {
  const res = await authFetch(`/api/v1/exclusions/${id}/reject?reason=${encodeURIComponent(reason)}`, { method: 'POST' });
  if (!res.ok) { const e = await res.json(); throw new Error(typeof e.detail === 'string' ? e.detail : JSON.stringify(e.detail) || 'Failed'); }
  return res.json();
};

type Tab = 'global' | 'agent' | 'pending';

export default function ExclusionsPage() {
  const qc = useQueryClient();
  const [tab, setTab] = useState<Tab>('global');
  const [selectedAgent, setSelectedAgent] = useState("");
  const [showModal, setShowModal] = useState(false);
  const [rejectModal, setRejectModal] = useState<{ id: string; name: string } | null>(null);
  const [rejectReason, setRejectReason] = useState("");
  const [toasts, setToasts] = useState<{ id: number; msg: string; ok: boolean }[]>([]);

  const [newRule, setNewRule] = useState({
    rule_name: '', rule_type: 'glob', match_value: '', reason: '', scope: 'global', agent_id: ''
  });

  const addToast = (msg: string, ok: boolean) => {
    const id = Date.now();
    setToasts(t => [...t, { id, msg, ok }]);
    setTimeout(() => setToasts(t => t.filter(x => x.id !== id)), 4000);
  };

  const invalidate = () => {
    qc.invalidateQueries({ queryKey: ["exclusions"] });
    qc.invalidateQueries({ queryKey: ["pending"] });
  };

  const { data: exclusionsData } = useQuery({
    queryKey: ["exclusions", tab === 'agent' ? 'agent' : 'global', selectedAgent],
    queryFn: () => fetchExclusions(tab === 'agent' ? 'agent' : 'global', selectedAgent),
    enabled: tab !== 'pending' && (tab === 'global' || !!selectedAgent)
  });

  const { data: pendingData } = useQuery({
    queryKey: ["pending"],
    queryFn: fetchPending,
    refetchInterval: 30_000,
  });

  const { data: agentsData } = useQuery({
    queryKey: ["agents"],
    queryFn: fetchAgents
  });

  const createMutation = useMutation({
    mutationFn: createExclusion,
    onSuccess: () => {
      setShowModal(false);
      setNewRule({ rule_name: '', rule_type: 'glob', match_value: '', reason: '', scope: 'global', agent_id: '' });
      invalidate();
      addToast("Rule submitted — awaiting admin approval", true);
    },
    onError: (e: any) => addToast(e.message, false)
  });

  const deleteMutation = useMutation({
    mutationFn: deleteExclusion,
    onSuccess: () => { invalidate(); addToast("Rule deleted", true); },
    onError: (e: any) => addToast(e.message, false)
  });

  const approveMutation = useMutation({
    mutationFn: approveRule,
    onSuccess: (_, id) => { invalidate(); addToast("Rule approved and now active", true); },
    onError: (e: any) => addToast(e.message, false)
  });

  const rejectMutation = useMutation({
    mutationFn: rejectRule,
    onSuccess: () => {
      setRejectModal(null); setRejectReason("");
      invalidate(); addToast("Rule rejected", true);
    },
    onError: (e: any) => addToast(e.message, false)
  });

  const agents = agentsData?.agents || [];
  const rules = Array.isArray(exclusionsData)
    ? exclusionsData
    : (exclusionsData?.agent_specific_rules || exclusionsData?.rules || []);
  const effectiveGlobal = exclusionsData?.global_rules || [];
  const pending: any[] = pendingData?.pending || [];
  const pendingCount = pendingData?.count || 0;

  return (
    <div className="space-y-6">
      {/* Toasts */}
      <div className="fixed top-4 right-4 z-50 space-y-2">
        {toasts.map(t => (
          <div key={t.id} className={`px-4 py-3 rounded-lg border text-sm shadow-lg ${
            t.ok ? "bg-green-900/90 border-green-700 text-green-200" : "bg-red-900/90 border-red-700 text-red-200"
          }`}>
            {t.ok ? "✅" : "❌"} {t.msg}
          </div>
        ))}
      </div>

      {/* Header */}
      <div className="flex justify-between items-center bg-slate-900 p-4 rounded-lg border border-slate-800">
        <div>
          <h1 className="text-xl font-bold text-white">Exclusion Management</h1>
          <p className="text-slate-400 text-sm">Manage files and directories to ignore during scans</p>
        </div>
        {tab !== 'pending' && (
          <button
            onClick={() => { setNewRule(r => ({ ...r, scope: tab === 'agent' ? 'agent' : 'global', agent_id: selectedAgent })); setShowModal(true); }}
            className="px-4 py-2 bg-blue-600 text-white rounded hover:bg-blue-700 flex items-center gap-2 text-sm"
          >
            <Plus size={16} /> Add Exclusion
          </button>
        )}
      </div>

      {/* Tabs */}
      <div className="flex border-b border-slate-800">
        {([
          { key: 'global', label: 'Global Rules', icon: Globe, color: 'blue' },
          { key: 'agent',  label: 'Agent Specific', icon: Server, color: 'green' },
          { key: 'pending', label: 'Pending Approval', icon: ShieldAlert, color: 'yellow', badge: pendingCount },
        ] as const).map(({ key, label, icon: Icon, color, badge }) => (
          <button key={key} onClick={() => setTab(key)}
            className={`px-6 py-3 text-sm font-medium flex items-center gap-2 border-b-2 transition-colors ${
              tab === key
                ? color === 'blue'   ? 'border-blue-500 text-blue-400'
                : color === 'green'  ? 'border-green-500 text-green-400'
                :                      'border-yellow-500 text-yellow-400'
                : 'border-transparent text-slate-400 hover:text-slate-200'
            }`}>
            <Icon size={16} />
            {label}
            {badge != null && badge > 0 && (
              <span className="ml-1 px-1.5 py-0.5 rounded-full bg-yellow-500 text-black text-xs font-bold">
                {badge}
              </span>
            )}
          </button>
        ))}
      </div>

      {/* Agent selector */}
      {tab === 'agent' && (
        <div className="bg-slate-900 p-4 rounded-lg border border-slate-800">
          <label className="text-sm text-slate-400 block mb-2">Select Agent:</label>
          <select
            className="w-full md:w-1/3 bg-slate-950 border border-slate-700 rounded p-2 text-white"
            value={selectedAgent}
            onChange={e => setSelectedAgent(e.target.value)}
          >
            <option value="">-- Select Agent --</option>
            {agents.map((a: any) => (
              <option key={a.id} value={a.id}>{a.hostname} ({a.ip_address})</option>
            ))}
          </select>
        </div>
      )}

      {/* Pending Approval Table */}
      {tab === 'pending' && (
        <div className="bg-slate-900 border border-slate-800 rounded-lg overflow-hidden">
          {pending.length === 0 ? (
            <div className="px-6 py-16 text-center text-slate-500">
              <CheckCircle size={32} className="mx-auto mb-3 text-green-600" />
              No pending exclusions — all rules are reviewed.
            </div>
          ) : (
            <table className="w-full text-sm text-left text-slate-300">
              <thead className="bg-slate-950/50 text-slate-400 font-semibold uppercase text-xs border-b border-slate-800">
                <tr>
                  <th className="px-6 py-4">Rule Name</th>
                  <th className="px-6 py-4">Type</th>
                  <th className="px-6 py-4">Pattern</th>
                  <th className="px-6 py-4">Reason</th>
                  <th className="px-6 py-4">Scope</th>
                  <th className="px-6 py-4">Submitted</th>
                  <th className="px-6 py-4">Submitted By</th>
                  <th className="px-6 py-4 text-right">Actions</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-slate-800">
                {pending.map((rule: any) => (
                  <tr key={rule.id} className="hover:bg-slate-800/50 bg-yellow-900/5">
                    <td className="px-6 py-4 font-medium text-white">{rule.rule_name}</td>
                    <td className="px-6 py-4">
                      <span className="px-2 py-1 bg-slate-800 rounded text-xs border border-slate-700">
                        {rule.rule_type}
                      </span>
                    </td>
                    <td className="px-6 py-4 font-mono text-xs text-orange-300">{rule.match_value}</td>
                    <td className="px-6 py-4 text-slate-400 max-w-[200px] truncate">{rule.reason}</td>
                    <td className="px-6 py-4">
                      <span className={`px-2 py-1 rounded text-xs border ${
                        rule.scope === 'global'
                          ? 'bg-blue-900/20 border-blue-800 text-blue-400'
                          : 'bg-green-900/20 border-green-800 text-green-400'
                      }`}>
                        {rule.scope}
                      </span>
                    </td>
                    <td className="px-6 py-4 text-slate-400 text-xs">
                      <div className="flex items-center gap-1">
                        <Clock size={11} />
                        {rule.created_at ? new Date(rule.created_at).toLocaleString() : '—'}
                      </div>
                    </td>
                    <td className="px-6 py-4 text-slate-400 text-xs">
                      {rule.created_by_username || '—'}
                    </td>
                    <td className="px-6 py-4 text-right">
                      <div className="flex items-center justify-end gap-2">
                        <button
                          onClick={() => approveMutation.mutate(rule.id)}
                          disabled={approveMutation.isPending}
                          className="inline-flex items-center gap-1 px-3 py-1.5 rounded text-xs font-medium bg-green-900/30 border border-green-700 text-green-300 hover:bg-green-900/60"
                        >
                          <CheckCircle size={12} /> Approve
                        </button>
                        <button
                          onClick={() => { setRejectModal({ id: rule.id, name: rule.rule_name }); setRejectReason(""); }}
                          className="inline-flex items-center gap-1 px-3 py-1.5 rounded text-xs font-medium bg-red-900/30 border border-red-700 text-red-300 hover:bg-red-900/60"
                        >
                          <XCircle size={12} /> Reject
                        </button>
                      </div>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </div>
      )}

      {/* Active Rules Table */}
      {tab !== 'pending' && (
        <div className="bg-slate-900 border border-slate-800 rounded-lg overflow-hidden">
          <table className="w-full text-sm text-left text-slate-300">
            <thead className="bg-slate-950/50 text-slate-400 font-semibold uppercase text-xs border-b border-slate-800">
              <tr>
                <th className="px-6 py-4">Rule Name</th>
                <th className="px-6 py-4">Type</th>
                <th className="px-6 py-4">Pattern</th>
                <th className="px-6 py-4">Reason</th>
                <th className="px-6 py-4 text-right">Actions</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-slate-800">
              {rules.map((rule: any) => (
                <tr key={rule.id} className="hover:bg-slate-800/50">
                  <td className="px-6 py-4 font-medium text-white">{rule.rule_name}</td>
                  <td className="px-6 py-4">
                    <span className="px-2 py-1 bg-slate-800 rounded text-xs border border-slate-700">
                      {rule.rule_type}
                    </span>
                  </td>
                  <td className="px-6 py-4 font-mono text-xs text-orange-300">{rule.match_value}</td>
                  <td className="px-6 py-4 text-slate-400">{rule.reason}</td>
                  <td className="px-6 py-4 text-right">
                    <button
                      onClick={() => { if (confirm('Delete rule?')) deleteMutation.mutate(rule.id); }}
                      className="p-2 text-red-400 hover:bg-red-900/20 rounded"
                    >
                      <Trash2 size={16} />
                    </button>
                  </td>
                </tr>
              ))}
              {rules.length === 0 && (
                <tr>
                  <td colSpan={5} className="px-6 py-12 text-center text-slate-500">
                    {tab === 'agent' && !selectedAgent
                      ? "Select an agent to view rules"
                      : "No approved exclusion rules."}
                  </td>
                </tr>
              )}
            </tbody>
          </table>
        </div>
      )}

      {/* Inherited global rules (agent tab) */}
      {tab === 'agent' && selectedAgent && effectiveGlobal.length > 0 && (
        <div>
          <h3 className="text-sm font-semibold text-slate-400 mb-3">Inherited Global Rules</h3>
          <div className="bg-slate-900 border border-slate-800 rounded-lg overflow-hidden opacity-70">
            <table className="w-full text-sm text-slate-300">
              <tbody className="divide-y divide-slate-800">
                {effectiveGlobal.map((rule: any) => (
                  <tr key={rule.id}>
                    <td className="px-6 py-3 font-medium">{rule.rule_name}</td>
                    <td className="px-6 py-3 font-mono text-xs text-orange-300">{rule.match_value}</td>
                    <td className="px-6 py-3 text-right text-xs italic text-slate-500">Global Rule</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      )}

      {/* Add Rule Modal */}
      {showModal && (
        <div className="fixed inset-0 bg-black/60 flex items-center justify-center z-50">
          <div className="bg-slate-900 border border-slate-700 rounded-lg p-6 w-[500px] shadow-xl">
            <h2 className="text-lg font-bold text-white mb-1">Add Exclusion Rule</h2>
            <p className="text-xs text-yellow-400 mb-4 flex items-center gap-1">
              <ShieldAlert size={12} /> Rule will be submitted for admin approval before taking effect.
            </p>
            <div className="space-y-4">
              <div>
                <label className="block text-xs text-slate-400 mb-1">Name</label>
                <input className="w-full bg-slate-950 border border-slate-700 rounded p-2 text-white"
                  value={newRule.rule_name}
                  onChange={e => setNewRule({ ...newRule, rule_name: e.target.value })} />
              </div>
              <div>
                <label className="block text-xs text-slate-400 mb-1">Type</label>
                <select className="w-full bg-slate-950 border border-slate-700 rounded p-2 text-white"
                  value={newRule.rule_type}
                  onChange={e => setNewRule({ ...newRule, rule_type: e.target.value })}>
                  <option value="path">Exact Path (/etc/passwd)</option>
                  <option value="glob">Glob Pattern (/var/log/*)</option>
                  <option value="regex">Regex (^/tmp/.*)</option>
                </select>
              </div>
              <div>
                <label className="block text-xs text-slate-400 mb-1">Match Pattern</label>
                <input className="w-full bg-slate-950 border border-slate-700 rounded p-2 text-white font-mono"
                  placeholder="/path/to/exclude"
                  value={newRule.match_value}
                  onChange={e => setNewRule({ ...newRule, match_value: e.target.value })} />
              </div>
              <div>
                <label className="block text-xs text-slate-400 mb-1">Reason</label>
                <input className="w-full bg-slate-950 border border-slate-700 rounded p-2 text-white"
                  value={newRule.reason}
                  onChange={e => setNewRule({ ...newRule, reason: e.target.value })} />
              </div>
              <div className="flex justify-end gap-2 mt-6">
                <button onClick={() => setShowModal(false)} className="px-4 py-2 text-slate-300 hover:text-white">Cancel</button>
                <button
                  onClick={() => createMutation.mutate(newRule)}
                  disabled={createMutation.isPending || !newRule.rule_name || !newRule.match_value}
                  className="px-4 py-2 bg-blue-600 text-white rounded hover:bg-blue-700 disabled:opacity-50"
                >
                  Submit for Approval
                </button>
              </div>
            </div>
          </div>
        </div>
      )}

      {/* Reject Modal */}
      {rejectModal && (
        <div className="fixed inset-0 bg-black/60 flex items-center justify-center z-50">
          <div className="bg-slate-900 border border-slate-700 rounded-lg p-6 w-[440px] shadow-xl">
            <h2 className="text-lg font-bold text-white mb-1">Reject Rule</h2>
            <p className="text-sm text-slate-400 mb-4">Rejecting: <span className="text-white font-medium">{rejectModal.name}</span></p>
            <label className="block text-xs text-slate-400 mb-1">Reason for rejection</label>
            <textarea
              className="w-full bg-slate-950 border border-slate-700 rounded p-2 text-white text-sm h-24 resize-none"
              placeholder="e.g. This path is security-sensitive and must not be excluded"
              value={rejectReason}
              onChange={e => setRejectReason(e.target.value)}
            />
            <div className="flex justify-end gap-2 mt-4">
              <button onClick={() => setRejectModal(null)} className="px-4 py-2 text-slate-300 hover:text-white">Cancel</button>
              <button
                onClick={() => rejectMutation.mutate({ id: rejectModal.id, reason: rejectReason })}
                disabled={rejectMutation.isPending}
                className="px-4 py-2 bg-red-700 text-white rounded hover:bg-red-600 disabled:opacity-50"
              >
                Confirm Reject
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
