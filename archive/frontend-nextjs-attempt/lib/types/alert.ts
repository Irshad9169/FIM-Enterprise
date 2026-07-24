export type AlertSeverity = 'critical' | 'high' | 'medium' | 'low';
export type AlertStatus = 'open' | 'acknowledged' | 'resolved';

export interface Alert {
  id: string;
  agent_id: string;
  agent_hostname: string;
  alert_type: string;
  severity: AlertSeverity;
  file_path: string;
  status: AlertStatus;
  change_details: Record<string, any> | null;
  previous_state: Record<string, any> | null;
  current_state: Record<string, any> | null;
  detected_at: string | null;
  created_at: string | null;
  acknowledged_at?: string | null;
  resolved_at?: string | null;
}

export interface AlertListResponse {
  alerts: Alert[];
  total: number;
  pagination: {
    limit: number;
    offset: number;
    has_more: boolean;
  };
}

export interface AlertStats {
  total_alerts: number;
  by_status: {
    open: number;
    acknowledged: number;
    resolved: number;
  };
  by_severity: {
    critical: number;
    high: number;
    medium: number;
    low: number;
  };
}
