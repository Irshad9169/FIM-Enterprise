import { apiClient } from './client';
import { BaselineListResponse, BaselineCreateRequest, Baseline } from '../types/baseline';

export const baselinesApi = {
  list: async (agent_id?: string): Promise<BaselineListResponse> => {
    const { data } = await apiClient.get<BaselineListResponse>('/baselines/list', {
      params: { agent_id },
    });
    return data;
  },

  create: async (request: BaselineCreateRequest) => {
    const { data } = await apiClient.post('/baselines/create', request);
    return data;
  },

  approve: async (baseline_id: string, notes?: string) => {
    const { data } = await apiClient.post('/baselines/approve', {
      baseline_id,
      notes,
    });
    return data;
  },

  getAgentBaseline: async (agent_id: string): Promise<Baseline> => {
    const { data } = await apiClient.get<Baseline>(`/baselines/agent/${agent_id}`);
    return data;
  },
};
