import { apiClient } from './client';

export interface AgentSearchResult {
  id: string;
  hostname: string;
  ip_address: string | null;
  status: string;
  last_heartbeat: string | null;
  last_scan_at: string | null;
  hours_since_scan: number | null;
  scan_needed: boolean;
  scan_count: number;
  is_healthy?: boolean; // Optional, only in recently-scanned response
}

export interface AgentSearchResponse {
  query: string;
  results: AgentSearchResult[];
  count: number;
}

export interface RecentlyScannedResponse {
  recently_scanned: AgentSearchResult[];
  count: number;
}

export interface ScanStatusResponse {
  agent_id: string;
  hostname: string;
  last_scan_at: string | null;
  hours_since_scan: number | null;
  scan_needed: boolean;
  total_scans: number;
  last_scan_status: string | null;
  last_scan_files: number | null;
}

export interface ScanRequestResponse {
  success: boolean;
  request_id: string;
  agent_id: string;
  agent_hostname: string;
  message: string;
  status: string;
}

export const agentsEnhancedApi = {
  search: async (query: string, limit: number = 10): Promise<AgentSearchResponse> => {
    const { data } = await apiClient.get<AgentSearchResponse>('/agents-enhanced/search', {
      params: { query, limit },
    });
    return data;
  },

  recentlyScanned: async (limit: number = 10): Promise<RecentlyScannedResponse> => {
    const { data } = await apiClient.get<RecentlyScannedResponse>(
      '/agents-enhanced/recently-scanned',
      { params: { limit } }
    );
    return data;
  },

  getScanStatus: async (agentId: string): Promise<ScanStatusResponse> => {
    const { data } = await apiClient.get<ScanStatusResponse>(
      `/agents-enhanced/scan-status/${agentId}`
    );
    return data;
  },
};
