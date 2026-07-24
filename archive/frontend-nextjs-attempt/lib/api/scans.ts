import { apiClient } from './client';
import { ScanListResponse, ScanDetail } from '../types/scan';

export const scansApi = {
  list: async (agent_id?: string, limit?: number): Promise<ScanListResponse> => {
    const { data } = await apiClient.get<ScanListResponse>('/scans', {
      params: { agent_id, limit },
    });
    return data;
  },

  getById: async (scan_id: string): Promise<ScanDetail> => {
    const { data } = await apiClient.get<ScanDetail>(`/scans/${scan_id}`);
    return data;
  },
};
