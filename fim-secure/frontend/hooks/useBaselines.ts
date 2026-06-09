import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import { baselinesApi } from '@/lib/api/baselines';
import { BaselineCreateRequest } from '@/lib/types/baseline';

export const useBaselines = (agent_id?: string) => {
  return useQuery({
    queryKey: ['baselines', agent_id],
    queryFn: () => baselinesApi.list(agent_id),
  });
};

export const useCreateBaseline = () => {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: (request: BaselineCreateRequest) => baselinesApi.create(request),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['baselines'] });
    },
  });
};

export const useApproveBaseline = () => {
  const queryClient = useQueryClient();

  return useMutation({
    mutationFn: ({ baseline_id, notes }: { baseline_id: string; notes?: string }) =>
      baselinesApi.approve(baseline_id, notes),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['baselines'] });
    },
  });
};
