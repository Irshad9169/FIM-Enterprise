'use client';

import { useAlertStats } from '@/hooks/useAlerts';
import { useAgentHealth } from '@/hooks/useAgents';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { Skeleton } from '@/components/ui/skeleton';
import { Header } from '@/components/layout/Header';
import { AlertTriangle, CheckCircle, Server, XCircle, Activity } from 'lucide-react';

export default function DashboardPage() {
  const { data: alertStats, isLoading: alertsLoading } = useAlertStats();
  const { data: agentHealth, isLoading: agentsLoading } = useAgentHealth();

  if (alertsLoading || agentsLoading) {
    return <DashboardSkeleton />;
  }

  return (
    <div className="flex flex-col h-full">
      <Header title="Dashboard Overview" />
      
      <div className="flex-1 p-6 space-y-6">
        {/* Stats Grid */}
        <div className="grid gap-4 md:grid-cols-2 lg:grid-cols-4">
          <StatsCard
            title="Total Alerts"
            value={alertStats?.total_alerts || 0}
            icon={<AlertTriangle className="h-4 w-4 text-yellow-600" />}
          />
          <StatsCard
            title="Open Alerts"
            value={alertStats?.by_status.open || 0}
            icon={<XCircle className="h-4 w-4 text-red-600" />}
            trend="critical"
          />
          <StatsCard
            title="Online Agents"
            value={agentHealth?.online_agents || 0}
            icon={<Server className="h-4 w-4 text-green-600" />}
          />
          <StatsCard
            title="Healthy Agents"
            value={agentHealth?.healthy_agents || 0}
            icon={<CheckCircle className="h-4 w-4 text-green-600" />}
          />
        </div>

        {/* Charts Grid */}
        <div className="grid gap-4 md:grid-cols-2">
          {/* Alert Severity */}
          <Card>
            <CardHeader>
              <CardTitle>Alerts by Severity</CardTitle>
            </CardHeader>
            <CardContent>
              <div className="space-y-3">
                <SeverityBar 
                  label="Critical" 
                  count={alertStats?.by_severity.critical || 0} 
                  total={alertStats?.total_alerts || 1}
                  color="bg-red-500" 
                />
                <SeverityBar 
                  label="High" 
                  count={alertStats?.by_severity.high || 0} 
                  total={alertStats?.total_alerts || 1}
                  color="bg-orange-500" 
                />
                <SeverityBar 
                  label="Medium" 
                  count={alertStats?.by_severity.medium || 0} 
                  total={alertStats?.total_alerts || 1}
                  color="bg-yellow-500" 
                />
                <SeverityBar 
                  label="Low" 
                  count={alertStats?.by_severity.low || 0} 
                  total={alertStats?.total_alerts || 1}
                  color="bg-blue-500" 
                />
              </div>
            </CardContent>
          </Card>

          {/* Alert Status */}
          <Card>
            <CardHeader>
              <CardTitle>Alert Status Distribution</CardTitle>
            </CardHeader>
            <CardContent>
              <div className="space-y-3">
                <StatusBar 
                  label="Open" 
                  count={alertStats?.by_status.open || 0} 
                  total={alertStats?.total_alerts || 1}
                  color="bg-red-500" 
                />
                <StatusBar 
                  label="Acknowledged" 
                  count={alertStats?.by_status.acknowledged || 0} 
                  total={alertStats?.total_alerts || 1}
                  color="bg-yellow-500" 
                />
                <StatusBar 
                  label="Resolved" 
                  count={alertStats?.by_status.resolved || 0} 
                  total={alertStats?.total_alerts || 1}
                  color="bg-green-500" 
                />
              </div>
            </CardContent>
          </Card>
        </div>

        {/* Agent Health Summary */}
        <Card>
          <CardHeader>
            <CardTitle>Agent Health Summary</CardTitle>
          </CardHeader>
          <CardContent>
            <div className="grid gap-4 md:grid-cols-3">
              <div className="flex items-center gap-3">
                <Activity className="h-8 w-8 text-green-500" />
                <div>
                  <p className="text-sm text-muted-foreground">Total Agents</p>
                  <p className="text-2xl font-bold">{agentHealth?.total_agents || 0}</p>
                </div>
              </div>
              <div className="flex items-center gap-3">
                <CheckCircle className="h-8 w-8 text-green-500" />
                <div>
                  <p className="text-sm text-muted-foreground">Healthy</p>
                  <p className="text-2xl font-bold">{agentHealth?.healthy_agents || 0}</p>
                </div>
              </div>
              <div className="flex items-center gap-3">
                <XCircle className="h-8 w-8 text-red-500" />
                <div>
                  <p className="text-sm text-muted-foreground">Unhealthy</p>
                  <p className="text-2xl font-bold">{agentHealth?.unhealthy_agents || 0}</p>
                </div>
              </div>
            </div>
          </CardContent>
        </Card>
      </div>
    </div>
  );
}

function StatsCard({ title, value, icon, trend }: any) {
  return (
    <Card>
      <CardHeader className="flex flex-row items-center justify-between space-y-0 pb-2">
        <CardTitle className="text-sm font-medium">{title}</CardTitle>
        {icon}
      </CardHeader>
      <CardContent>
        <div className="text-2xl font-bold">{value}</div>
      </CardContent>
    </Card>
  );
}

function SeverityBar({ label, count, total, color }: any) {
  const percentage = total > 0 ? (count / total) * 100 : 0;
  
  return (
    <div className="space-y-1">
      <div className="flex items-center justify-between text-sm">
        <span className="font-medium">{label}</span>
        <span className="text-muted-foreground">{count}</span>
      </div>
      <div className="h-2 w-full bg-gray-100 rounded-full overflow-hidden">
        <div 
          className={`h-full ${color} transition-all`}
          style={{ width: `${percentage}%` }}
        />
      </div>
    </div>
  );
}

function StatusBar({ label, count, total, color }: any) {
  return <SeverityBar label={label} count={count} total={total} color={color} />;
}

function DashboardSkeleton() {
  return (
    <div className="flex flex-col h-full">
      <Header title="Dashboard Overview" />
      <div className="flex-1 p-6 space-y-6">
        <div className="grid gap-4 md:grid-cols-4">
          {[...Array(4)].map((_, i) => (
            <Skeleton key={i} className="h-32" />
          ))}
        </div>
        <div className="grid gap-4 md:grid-cols-2">
          {[...Array(2)].map((_, i) => (
            <Skeleton key={i} className="h-64" />
          ))}
        </div>
      </div>
    </div>
  );
}
