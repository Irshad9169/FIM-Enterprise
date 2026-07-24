import { apiClient } from './client';
import { AgentListResponse, AgentHealthSummary } from '../types/agent';

export const agentsApi = {
  list: async (status?: string): Promise<AgentListResponse> => {
    const { data } = await apiClient.get<AgentListResponse>('/agents', {
      params: { status },
    });
    return data;
  },

  getHealthSummary: async (): Promise<AgentHealthSummary> => {
    const { data } = await apiClient.get<AgentHealthSummary>('/agents/health/summary');
    return data;
  },
};
