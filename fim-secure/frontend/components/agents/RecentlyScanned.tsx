'use client';

import { useRecentlyScanned } from '@/hooks/useAgentsEnhanced';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { Badge } from '@/components/ui/badge';
import { Skeleton } from '@/components/ui/skeleton';
import { Clock, Server } from 'lucide-react';
import { formatRelativeTime } from '@/lib/utils/format';

export function RecentlyScanned() {
  const { data, isLoading } = useRecentlyScanned(10);

  if (isLoading) {
    return (
      <Card>
        <CardHeader>
          <CardTitle>Recently Scanned Agents</CardTitle>
        </CardHeader>
        <CardContent>
          <div className="space-y-3">
            {[...Array(5)].map((_, i) => (
              <Skeleton key={i} className="h-16" />
            ))}
          </div>
        </CardContent>
      </Card>
    );
  }

  if (!data || data.count === 0) {
    return (
      <Card>
        <CardHeader>
          <CardTitle>Recently Scanned Agents</CardTitle>
        </CardHeader>
        <CardContent>
          <div className="text-center py-8 text-muted-foreground">
            <Server className="h-12 w-12 mx-auto mb-2 opacity-50" />
            <p>No recent scans found</p>
          </div>
        </CardContent>
      </Card>
    );
  }

  return (
    <Card>
      <CardHeader>
        <CardTitle className="flex items-center justify-between">
          <span>Recently Scanned Agents</span>
          <Badge variant="outline">{data.count} total</Badge>
        </CardTitle>
      </CardHeader>
      <CardContent>
        <div className="space-y-3">
          {data.recently_scanned.map((agent) => (
            <div
              key={agent.id}
              className="flex items-center justify-between p-3 border rounded-lg hover:bg-accent/50 transition-colors"
            >
              <div className="flex-1">
                <div className="flex items-center gap-2">
                  <h4 className="font-medium text-sm">{agent.hostname}</h4>
                  {agent.status === 'online' && (
                    <div className="h-2 w-2 rounded-full bg-green-500" />
                  )}
                </div>
                <div className="flex items-center gap-2 mt-1">
                  <Clock className="h-3 w-3 text-muted-foreground" />
                  <span className="text-xs text-muted-foreground">
                    {formatRelativeTime(agent.last_scan_at)}
                  </span>
                  {agent.is_healthy !== false && (
                    <Badge className="bg-green-100 text-green-800 text-xs" variant="outline">
                      Healthy
                    </Badge>
                  )}
                </div>
              </div>
              <div className="text-right">
                <p className="text-xs text-muted-foreground">
                  {agent.scan_count} scan{agent.scan_count !== 1 ? 's' : ''}
                </p>
              </div>
            </div>
          ))}
        </div>
      </CardContent>
    </Card>
  );
}
