import { Badge } from "@/components/ui/badge";
import { AlertSeverity } from "@/lib/types/alert";

interface SeverityBadgeProps {
  severity: AlertSeverity;
}

const severityConfig = {
  critical: { label: "Critical", className: "bg-red-600 text-white hover:bg-red-700" },
  high: { label: "High", className: "bg-orange-500 text-white hover:bg-orange-600" },
  medium: { label: "Medium", className: "bg-yellow-500 text-white hover:bg-yellow-600" },
  low: { label: "Low", className: "bg-blue-500 text-white hover:bg-blue-600" },
};

export function SeverityBadge({ severity }: SeverityBadgeProps) {
  const config = severityConfig[severity];
  
  return (
    <Badge className={config.className}>
      {config.label}
    </Badge>
  );
}
