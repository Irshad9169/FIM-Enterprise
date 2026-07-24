import { apiClient } from './client';
import { AlertListResponse, AlertStats } from '../types/alert';

export const alertsApi = {
  list: async (params?: {
    status?: string;
    severity?: string;
    days?: number;
    limit?: number;
    offset?: number;
  }): Promise<AlertListResponse> => {
    const { data } = await apiClient.get<AlertListResponse>('/alerts', { params });
    return data;
  },

  getStats: async (): Promise<AlertStats> => {
    const { data } = await apiClient.get<AlertStats>('/alerts/actions/stats');
    return data;
  },

  acknowledge: async (alert_id: string, notes?: string) => {
    const { data } = await apiClient.post('/alerts/actions/acknowledge', {
      alert_id,
      notes,
    });
    return data;
  },

  bulkAcknowledge: async (alert_ids: string[], notes?: string) => {
    const { data } = await apiClient.post('/alerts/actions/acknowledge/bulk', {
      alert_ids,
      notes,
    });
    return data;
  },

  resolve: async (alert_id: string, resolution_notes: string) => {
    const { data } = await apiClient.post('/alerts/actions/resolve', {
      alert_id,
      resolution_notes,
    });
    return data;
  },
};
