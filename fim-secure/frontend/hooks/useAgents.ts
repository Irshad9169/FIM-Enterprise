import { useQuery } from '@tanstack/react-query';
import { agentsApi } from '@/lib/api/agents';

export const useAgents = (status?: string) => {
  return useQuery({
    queryKey: ['agents', status],
    queryFn: () => agentsApi.list(status),
    refetchInterval: 30000,
  });
};

export const useAgentHealth = () => {
  return useQuery({
    queryKey: ['agent-health'],
    queryFn: () => agentsApi.getHealthSummary(),
    refetchInterval: 30000,
  });
};
