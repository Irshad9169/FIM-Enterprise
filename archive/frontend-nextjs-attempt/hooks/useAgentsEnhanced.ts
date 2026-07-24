import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { agentsEnhancedApi } from '@/lib/api/agents_enhanced';
import { scanRequestsApi } from '@/lib/api/scan_requests';

export const useAgentSearch = (query: string, enabled: boolean = true) => {
  return useQuery({
    queryKey: ['agent-search', query],
    queryFn: () => agentsEnhancedApi.search(query),
    enabled: enabled && query.length >= 2,
    staleTime: 30000,
  });
};

export const useRecentlyScanned = (limit: number = 10) => {
  return useQuery({
    queryKey: ['recently-scanned', limit],
    queryFn: () => agentsEnhancedApi.recentlyScanned(limit),
    refetchInterval: 60000, // Refresh every minute
  });
};

export const useScanStatus = (agentId: string, enabled: boolean = true) => {
  return useQuery({
    queryKey: ['scan-status', agentId],
    queryFn: () => agentsEnhancedApi.getScanStatus(agentId),
    enabled: enabled && !!agentId,
  });
};

export const useTriggerScan = () => {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: (agentId: string) => scanRequestsApi.triggerScan(agentId),
    onSuccess: () => {
      // Invalidate relevant queries
      queryClient.invalidateQueries({ queryKey: ['agents'] });
      queryClient.invalidateQueries({ queryKey: ['recently-scanned'] });
      queryClient.invalidateQueries({ queryKey: ['scan-status'] });
    },
  });
};

export const useScanRequestStatus = (agentId: string, enabled: boolean = true) => {
  return useQuery({
    queryKey: ['scan-request-status', agentId],
    queryFn: () => scanRequestsApi.getStatus(agentId),
    enabled: enabled && !!agentId,
    refetchInterval: 10000, // Check every 10 seconds
  });
};
