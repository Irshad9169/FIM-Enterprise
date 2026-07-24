export const ALERT_SEVERITIES = ['critical', 'high', 'medium', 'low'] as const;
export const ALERT_STATUSES = ['open', 'acknowledged', 'resolved'] as const;

export const SEVERITY_COLORS = {
  critical: 'bg-red-500',
  high: 'bg-orange-500',
  medium: 'bg-yellow-500',
  low: 'bg-blue-500',
} as const;

export const STATUS_COLORS = {
  open: 'bg-red-100 text-red-800',
  acknowledged: 'bg-yellow-100 text-yellow-800',
  resolved: 'bg-green-100 text-green-800',
} as const;
