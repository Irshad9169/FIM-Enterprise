import { useState, useEffect } from 'react';
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { 
  Plus, Trash2, Download, Upload, 
  ToggleLeft, ToggleRight, Globe, Server, Save, X 
} from 'lucide-react';

// API Functions
const fetchExclusions = async (scope: string, agentId?: string) => {
  const token = localStorage.getItem("fim_token");
  const url = scope === 'agent' && agentId 
    ? `/api/v1/exclusions/agents/${agentId}` 
    : '/api/v1/exclusions/global';
    
  const res = await fetch(url, {
    headers: { 'Authorization': `Bearer ${token}` }
  });
  return res.json();
};

const fetchAgents = async () => {
  const token = localStorage.getItem("fim_token");
  const res = await fetch('/api/v1/agents', {
    headers: { 'Authorization': `Bearer ${token}` }
  });
  return res.json();
};

const createExclusion = async (data: any) => {
  const token = localStorage.getItem("fim_token");
  const url = data.scope === 'agent' 
    ? `/api/v1/exclusions/agents/${data.agent_id}` 
    : '/api/v1/exclusions/global';

  const res = await fetch(url, {
    method: 'POST',
    headers: { 
      'Authorization': `Bearer ${token}`,
      'Content-Type': 'application/json' 
    },
    body: JSON.stringify(data)
  });
  if (!res.ok) {
    const err = await res.json();
    const msg = err.detail || err.message || JSON.stringify(err); throw new Error(msg);
  }
  return res.json();
};

const deleteExclusion = async (id: string) => {
  const token = localStorage.getItem("fim_token");
  const res = await fetch(`/api/v1/exclusions/${id}`, {
    method: 'DELETE',
    headers: { 'Authorization': `Bearer ${token}` }
  });
  if (!res.ok) throw new Error("Failed to delete");
};

export default function ExclusionsPage() {
  const queryClient = useQueryClient();
  const [scope, setScope] = useState('global');
  const [selectedAgent, setSelectedAgent] = useState("");
  const [showModal, setShowModal] = useState(false);
  
  // New Rule State
  const [newRule, setNewRule] = useState({
    rule_name: '',
    rule_type: 'path',
    match_value: '',
    reason: '',
    scope: 'global',
    agent_id: ''
  });

  // Queries
  const { data: exclusionsData } = useQuery({
    queryKey: ["exclusions", scope, selectedAgent],
    queryFn: () => fetchExclusions(scope, selectedAgent),
    enabled: scope === 'global' || !!selectedAgent
  });

  const { data: agentsData } = useQuery({
    queryKey: ["agents"],
    queryFn: fetchAgents
  });

  // Mutations
  const createMutation = useMutation({
    mutationFn: (rule: any) => {
      const cleaned = {...rule};
      if (cleaned.scope === 'global' || !cleaned.agent_id) {
        cleaned.agent_id = null;
      }
      return createExclusion(cleaned);
    },
    onSuccess: () => {
      setShowModal(false);
      setNewRule({ rule_name: '', rule_type: 'path', match_value: '', reason: '', scope: 'global', agent_id: '' });
      queryClient.invalidateQueries({ queryKey: ["exclusions"] });
    },
    onError: (err: any) => alert(err.message)
  });

  const deleteMutation = useMutation({
    mutationFn: deleteExclusion,
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ["exclusions"] })
  });

  // Derived Data
  const agents = agentsData?.agents || [];
  // Handle different API response structures (list vs object with keys)
  const rules = Array.isArray(exclusionsData) 
    ? exclusionsData 
    : (exclusionsData?.agent_specific_rules || []);

  const effectiveGlobal = exclusionsData?.global_rules || [];

  return (
    <div className="space-y-6">
      {/* Header */}
      <div className="flex justify-between items-center bg-slate-900 p-4 rounded-lg border border-slate-800">
        <div>
          <h1 className="text-xl font-bold text-white">Exclusion Management</h1>
          <p className="text-slate-400 text-sm">Manage files and directories to ignore during scans</p>
        </div>
        <button
          onClick={() => {
            setNewRule(prev => ({...prev, scope: scope, agent_id: selectedAgent}));
            setShowModal(true);
          }}
          className="px-4 py-2 bg-blue-600 text-white rounded hover:bg-blue-700 flex items-center gap-2"
        >
          <Plus size={16} /> Add Exclusion
        </button>
      </div>

      {/* Tabs */}
      <div className="flex border-b border-slate-800">
        <button
          onClick={() => { setScope('global'); setSelectedAgent(""); }}
          className={`px-6 py-3 text-sm font-medium flex items-center gap-2 ${
            scope === 'global' ? 'border-b-2 border-blue-500 text-blue-400' : 'text-slate-400 hover:text-slate-200'
          }`}
        >
          <Globe size={16} /> Global Rules
        </button>
        <button
          onClick={() => setScope('agent')}
          className={`px-6 py-3 text-sm font-medium flex items-center gap-2 ${
            scope === 'agent' ? 'border-b-2 border-green-500 text-green-400' : 'text-slate-400 hover:text-slate-200'
          }`}
        >
          <Server size={16} /> Agent Specific
        </button>
      </div>

      {/* Agent Selection */}
      {scope === 'agent' && (
        <div className="bg-slate-900 p-4 rounded-lg border border-slate-800">
          <label className="text-sm text-slate-400 block mb-2">Select Agent to Configure:</label>
          <select
            className="w-full md:w-1/3 bg-slate-950 border border-slate-700 rounded p-2 text-white"
            value={selectedAgent}
            onChange={(e) => setSelectedAgent(e.target.value)}
          >
            <option value="">-- Select Agent --</option>
            {agents.map((agent: any) => (
              <option key={agent.id} value={agent.id}>{agent.hostname} ({agent.ip_address})</option>
            ))}
          </select>
        </div>
      )}

      {/* Rules Table */}
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
                    onClick={() => {
                      if(confirm('Delete rule?')) deleteMutation.mutate(rule.id);
                    }}
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
                  {scope === 'agent' && !selectedAgent 
                    ? "Select an agent to view rules" 
                    : "No exclusion rules found."}
                </td>
              </tr>
            )}
          </tbody>
        </table>
      </div>

      {/* Show inherited global rules when viewing agent */}
      {scope === 'agent' && selectedAgent && effectiveGlobal.length > 0 && (
        <div className="mt-8">
          <h3 className="text-lg font-bold text-slate-400 mb-4">Inherited Global Rules</h3>
          <div className="bg-slate-900 border border-slate-800 rounded-lg overflow-hidden opacity-75">
            <table className="w-full text-sm text-left text-slate-300">
              <tbody className="divide-y divide-slate-800">
                {effectiveGlobal.map((rule: any) => (
                  <tr key={rule.id}>
                    <td className="px-6 py-3">{rule.rule_name}</td>
                    <td className="px-6 py-3 font-mono text-xs">{rule.match_value}</td>
                    <td className="px-6 py-3 text-right text-xs italic text-slate-500">Global Rule</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      )}

      {/* Add Modal */}
      {showModal && (
        <div className="fixed inset-0 bg-black/50 flex items-center justify-center z-50">
          <div className="bg-slate-900 border border-slate-700 rounded-lg p-6 w-[500px] shadow-xl">
            <h2 className="text-lg font-bold text-white mb-4">Add Exclusion Rule</h2>
            <div className="space-y-4">
              <div>
                <label className="block text-xs text-slate-400 mb-1">Name</label>
                <input 
                  className="w-full bg-slate-950 border border-slate-700 rounded p-2 text-white"
                  value={newRule.rule_name}
                  onChange={e => setNewRule({...newRule, rule_name: e.target.value})}
                />
              </div>
              <div>
                <label className="block text-xs text-slate-400 mb-1">Type</label>
                <select 
                  className="w-full bg-slate-950 border border-slate-700 rounded p-2 text-white"
                  value={newRule.rule_type}
                  onChange={e => setNewRule({...newRule, rule_type: e.target.value})}
                >
                  <option value="path">Exact Path (/etc/passwd)</option>
                  <option value="glob">Glob Pattern (/var/log/*)</option>
                  <option value="regex">Regex (^/tmp/.*)</option>
                </select>
              </div>
              <div>
                <label className="block text-xs text-slate-400 mb-1">Match Pattern</label>
                <input 
                  className="w-full bg-slate-950 border border-slate-700 rounded p-2 text-white font-mono"
                  placeholder="/path/to/exclude"
                  value={newRule.match_value}
                  onChange={e => setNewRule({...newRule, match_value: e.target.value})}
                />
              </div>
              <div>
                <label className="block text-xs text-slate-400 mb-1">Reason</label>
                <input 
                  className="w-full bg-slate-950 border border-slate-700 rounded p-2 text-white"
                  value={newRule.reason}
                  onChange={e => setNewRule({...newRule, reason: e.target.value})}
                />
              </div>
              
              <div className="flex justify-end gap-2 mt-6">
                <button 
                  onClick={() => setShowModal(false)}
                  className="px-4 py-2 text-slate-300 hover:text-white"
                >
                  Cancel
                </button>
                <button 
                  onClick={() => createMutation.mutate(newRule)}
                  className="px-4 py-2 bg-blue-600 text-white rounded hover:bg-blue-700"
                >
                  Create Rule
                </button>
              </div>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
