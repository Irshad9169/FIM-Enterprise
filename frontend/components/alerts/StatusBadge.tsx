import { Badge } from "@/components/ui/badge";
import { AlertStatus } from "@/lib/types/alert";

interface StatusBadgeProps {
  status: AlertStatus;
}

const statusConfig = {
  open: { label: "Open", className: "bg-red-100 text-red-800 border-red-200" },
  acknowledged: { label: "Acknowledged", className: "bg-yellow-100 text-yellow-800 border-yellow-200" },
  resolved: { label: "Resolved", className: "bg-green-100 text-green-800 border-green-200" },
};

export function StatusBadge({ status }: StatusBadgeProps) {
  const config = statusConfig[status];
  
  return (
    <Badge variant="outline" className={config.className}>
      {config.label}
    </Badge>
  );
}
