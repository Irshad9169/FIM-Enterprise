import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { alertsApi } from '@/lib/api/alerts';

export const useAlerts = (params?: {
  status?: string;
  severity?: string;
  days?: number;
  limit?: number;
  offset?: number;
}) => {
  return useQuery({
    queryKey: ['alerts', params],
    queryFn: () => alertsApi.list(params),
    refetchInterval: 30000, // Refresh every 30s
  });
};

export const useAlertStats = () => {
  return useQuery({
    queryKey: ['alert-stats'],
    queryFn: () => alertsApi.getStats(),
    refetchInterval: 30000,
  });
};

export const useAcknowledgeAlert = () => {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: ({ alert_id, notes }: { alert_id: string; notes?: string }) =>
      alertsApi.acknowledge(alert_id, notes),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['alerts'] });
      queryClient.invalidateQueries({ queryKey: ['alert-stats'] });
    },
  });
};

export const useResolveAlert = () => {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: ({ alert_id, resolution_notes }: { alert_id: string; resolution_notes: string }) =>
      alertsApi.resolve(alert_id, resolution_notes),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['alerts'] });
      queryClient.invalidateQueries({ queryKey: ['alert-stats'] });
    },
  });
};

export const useBulkAcknowledge = () => {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: ({ alert_ids, notes }: { alert_ids: string[]; notes?: string }) =>
      alertsApi.bulkAcknowledge(alert_ids, notes),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['alerts'] });
      queryClient.invalidateQueries({ queryKey: ['alert-stats'] });
    },
  });
};
