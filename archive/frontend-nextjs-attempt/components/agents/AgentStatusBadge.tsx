import { Badge } from "@/components/ui/badge";

interface AgentStatusBadgeProps {
  status: 'online' | 'offline';
}

export function AgentStatusBadge({ status }: AgentStatusBadgeProps) {
  if (status === 'online') {
    return (
      <Badge className="bg-green-100 text-green-800 border-green-200" variant="outline">
        Online
      </Badge>
    );
  }
  
  return (
    <Badge className="bg-gray-100 text-gray-800 border-gray-200" variant="outline">
      Offline
    </Badge>
  );
}
