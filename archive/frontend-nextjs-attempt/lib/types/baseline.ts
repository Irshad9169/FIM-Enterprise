export interface Baseline {
  id: string;
  agent_id: string;
  baseline_name: string;
  file_count: number;
  created_at: string | null;
  is_active: boolean;
  is_approved: boolean;
  approved_at: string | null;
  notes: string | null;
}

export interface BaselineListResponse {
  baselines: Baseline[];
  total: number;
}

export interface BaselineCreateRequest {
  agent_id: string;
  scan_id: string;
  baseline_name: string;
  notes?: string;
}
