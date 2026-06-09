export interface Agent {
  id: string;
  hostname: string;
  ip_address: string | null;
  os_type: string | null;
  os_version: string | null;
  agent_version: string | null;
  status: 'online' | 'offline';
  last_heartbeat: string | null;
  created_at: string | null;
  is_healthy?: boolean;
  expected_heartbeat_interval?: number;
  heartbeat_timeout?: number;
}

export interface AgentListResponse {
  agents: Agent[];
  total: number;
}

export interface AgentHealthSummary {
  total_agents: number;
  online_agents: number;
  offline_agents: number;
  healthy_agents: number;
  unhealthy_agents: number;
  stale_agents: number;
}
