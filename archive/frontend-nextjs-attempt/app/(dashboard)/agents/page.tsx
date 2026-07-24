'use client';

import { useState } from 'react';
import { useAgents } from '@/hooks/useAgents';
import { Header } from '@/components/layout/Header';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table';
import { Skeleton } from '@/components/ui/skeleton';
import { AgentStatusBadge } from '@/components/agents/AgentStatusBadge';
import { AgentSearch } from '@/components/agents/AgentSearch';
import { RecentlyScanned } from '@/components/agents/RecentlyScanned';
import { ScanNowButton } from '@/components/agents/ScanNowButton';
import { formatRelativeTime } from '@/lib/utils/format';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Server, RefreshCw, Clock, AlertCircle, CheckCircle } from 'lucide-react';

export default function AgentsPage() {
  const [statusFilter, setStatusFilter] = useState<string | undefined>();
  const { data, isLoading, refetch } = useAgents(statusFilter);

  if (isLoading) {
    return <AgentsSkeleton />;
  }

  const agents = data?.agents || [];

  return (
    <div className="flex flex-col h-full">
      <Header title="Agents" />
      
      <div className="flex-1 p-6 space-y-6">
        {/* Recently Scanned Section */}
        <div className="grid gap-6 md:grid-cols-3">
          <div className="md:col-span-2">
            <RecentlyScanned />
          </div>
          
          {/* Summary Cards */}
          <div className="space-y-4">
            <Card>
              <CardHeader className="flex flex-row items-center justify-between space-y-0 pb-2">
                <CardTitle className="text-sm font-medium">Total Agents</CardTitle>
                <Server className="h-4 w-4 text-muted-foreground" />
              </CardHeader>
              <CardContent>
                <div className="text-2xl font-bold">{data?.total || 0}</div>
              </CardContent>
            </Card>

            <Card>
              <CardHeader className="flex flex-row items-center justify-between space-y-0 pb-2">
                <CardTitle className="text-sm font-medium">Online</CardTitle>
                <div className="h-3 w-3 rounded-full bg-green-500" />
              </CardHeader>
              <CardContent>
                <div className="text-2xl font-bold">
                  {agents.filter(a => a.status === 'online').length}
                </div>
              </CardContent>
            </Card>

            <Card>
              <CardHeader className="flex flex-row items-center justify-between space-y-0 pb-2">
                <CardTitle className="text-sm font-medium">Offline</CardTitle>
                <div className="h-3 w-3 rounded-full bg-gray-400" />
              </CardHeader>
              <CardContent>
                <div className="text-2xl font-bold">
                  {agents.filter(a => a.status === 'offline').length}
                </div>
              </CardContent>
            </Card>
          </div>
        </div>

        {/* Search Section */}
        <AgentSearch />

        {/* Agent List Table */}
        <Card>
          <CardHeader>
            <div className="flex items-center justify-between">
              <CardTitle>All Agents</CardTitle>
              <div className="flex gap-2">
                <Button
                  variant={statusFilter === undefined ? "default" : "outline"}
                  size="sm"
                  onClick={() => setStatusFilter(undefined)}
                >
                  All
                </Button>
                <Button
                  variant={statusFilter === 'online' ? "default" : "outline"}
                  size="sm"
                  onClick={() => setStatusFilter('online')}
                >
                  Online
                </Button>
                <Button
                  variant={statusFilter === 'offline' ? "default" : "outline"}
                  size="sm"
                  onClick={() => setStatusFilter('offline')}
                >
                  Offline
                </Button>
                <Button
                  variant="outline"
                  size="sm"
                  onClick={() => refetch()}
                >
                  <RefreshCw className="h-4 w-4" />
                </Button>
              </div>
            </div>
          </CardHeader>
          <CardContent>
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>Hostname</TableHead>
                  <TableHead>IP Address</TableHead>
                  <TableHead>OS</TableHead>
                  <TableHead>Version</TableHead>
                  <TableHead>Status</TableHead>
                  <TableHead>Last Scan</TableHead>
                  <TableHead>Health</TableHead>
                  <TableHead>Actions</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {agents.length === 0 ? (
                  <TableRow>
                    <TableCell colSpan={8} className="text-center text-muted-foreground">
                      No agents found
                    </TableCell>
                  </TableRow>
                ) : (
                  agents.map((agent) => {
                    // Calculate scan status (since API doesn't return it in list)
                    const scanNeeded = true; // Default
                    const hoursSinceScan = null;

                    return (
                      <TableRow key={agent.id}>
                        <TableCell className="font-medium">{agent.hostname}</TableCell>
                        <TableCell>{agent.ip_address || 'N/A'}</TableCell>
                        <TableCell>
                          {agent.os_type ? (
                            <div className="flex flex-col">
                              <span>{agent.os_type}</span>
                              {agent.os_version && (
                                <span className="text-xs text-muted-foreground">
                                  {agent.os_version}
                                </span>
                              )}
                            </div>
                          ) : (
                            'N/A'
                          )}
                        </TableCell>
                        <TableCell>
                          {agent.agent_version ? (
                            <Badge variant="outline">{agent.agent_version}</Badge>
                          ) : (
                            'N/A'
                          )}
                        </TableCell>
                        <TableCell>
                          <AgentStatusBadge status={agent.status} />
                        </TableCell>
                        <TableCell>
                          <div className="flex items-center gap-2">
                            <Clock className="h-4 w-4 text-muted-foreground" />
                            <span className="text-sm text-muted-foreground">
                              {formatRelativeTime(agent.last_heartbeat)}
                            </span>
                          </div>
                        </TableCell>
                        <TableCell>
                          {agent.is_healthy !== false ? (
                            <Badge className="bg-green-100 text-green-800 border-green-200" variant="outline">
                              <CheckCircle className="h-3 w-3 mr-1" />
                              Healthy
                            </Badge>
                          ) : (
                            <Badge className="bg-red-100 text-red-800 border-red-200" variant="outline">
                              <AlertCircle className="h-3 w-3 mr-1" />
                              Unhealthy
                            </Badge>
                          )}
                        </TableCell>
                        <TableCell>
                          <ScanNowButton
                            agentId={agent.id}
                            agentHostname={agent.hostname}
                            scanNeeded={scanNeeded}
                            hoursSinceScan={hoursSinceScan}
                          />
                        </TableCell>
                      </TableRow>
                    );
                  })
                )}
              </TableBody>
            </Table>
          </CardContent>
        </Card>
      </div>
    </div>
  );
}

function AgentsSkeleton() {
  return (
    <div className="flex flex-col h-full">
      <Header title="Agents" />
      <div className="flex-1 p-6 space-y-6">
        <div className="grid gap-4 md:grid-cols-3">
          {[...Array(3)].map((_, i) => (
            <Skeleton key={i} className="h-24" />
          ))}
        </div>
        <Skeleton className="h-96" />
      </div>
    </div>
  );
}
