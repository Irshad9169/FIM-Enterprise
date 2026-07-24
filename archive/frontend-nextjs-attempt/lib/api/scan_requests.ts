import { apiClient } from './client';

export interface ScanRequestResponse {
  success: boolean;
  request_id: string;
  agent_id: string;
  agent_hostname: string;
  message: string;
  status: string;
}

export interface ScanRequestStatus {
  agent_id: string;
  requests: {
    request_id: string;
    status: string;
    requested_at: string;
    acknowledged_at: string | null;
    completed_at: string | null;
    error_message: string | null;
  }[];
}

export const scanRequestsApi = {
  triggerScan: async (agentId: string): Promise<ScanRequestResponse> => {
    const { data } = await apiClient.post<ScanRequestResponse>(
      `/scan-requests/trigger/${agentId}`
    );
    return data;
  },

  getStatus: async (agentId: string): Promise<ScanRequestStatus> => {
    const { data } = await apiClient.get<ScanRequestStatus>(
      `/scan-requests/status/${agentId}`
    );
    return data;
  },
};
