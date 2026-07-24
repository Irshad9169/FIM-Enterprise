import { useQuery } from '@tanstack/react-query';
import { scansApi } from '@/lib/api/scans';

export const useScans = (agent_id?: string, limit?: number) => {
  return useQuery({
    queryKey: ['scans', agent_id, limit],
    queryFn: () => scansApi.list(agent_id, limit),
  });
};

export const useScanDetail = (scan_id: string) => {
  return useQuery({
    queryKey: ['scan', scan_id],
    queryFn: () => scansApi.getById(scan_id),
    enabled: !!scan_id,
  });
};
