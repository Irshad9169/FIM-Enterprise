'use client';

import { useState } from 'react';
import { useAlerts, useAcknowledgeAlert, useResolveAlert, useBulkAcknowledge } from '@/hooks/useAlerts';
import { Header } from '@/components/layout/Header';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table';
import { Skeleton } from '@/components/ui/skeleton';
import { SeverityBadge } from '@/components/alerts/SeverityBadge';
import { StatusBadge } from '@/components/alerts/StatusBadge';
import { Button } from '@/components/ui/button';
import { formatDate, formatRelativeTime } from '@/lib/utils/format';
import { AlertSeverity, AlertStatus } from '@/lib/types/alert';
import { CheckCircle, XCircle, FileText } from 'lucide-react';
import { Badge } from '@/components/ui/badge';

export default function AlertsPage() {
  const [statusFilter, setStatusFilter] = useState<AlertStatus | undefined>('open');
  const [severityFilter, setSeverityFilter] = useState<AlertSeverity | undefined>();
  const [selectedAlerts, setSelectedAlerts] = useState<Set<string>>(new Set());

  const { data, isLoading, refetch } = useAlerts({
    status: statusFilter,
    severity: severityFilter,
    limit: 100,
  });

  const acknowledgeMutation = useAcknowledgeAlert();
  const resolveMutation = useResolveAlert();
  const bulkAcknowledgeMutation = useBulkAcknowledge();

  const alerts = data?.alerts || [];

  const handleAcknowledge = async (alertId: string) => {
    try {
      await acknowledgeMutation.mutateAsync({ alert_id: alertId });
      refetch();
    } catch (error) {
      console.error('Failed to acknowledge alert:', error);
    }
  };

  const handleResolve = async (alertId: string) => {
    const notes = prompt('Resolution notes:');
    if (!notes) return;

    try {
      await resolveMutation.mutateAsync({ alert_id: alertId, resolution_notes: notes });
      refetch();
    } catch (error) {
      console.error('Failed to resolve alert:', error);
    }
  };

  const handleBulkAcknowledge = async () => {
    if (selectedAlerts.size === 0) return;

    try {
      await bulkAcknowledgeMutation.mutateAsync({ 
        alert_ids: Array.from(selectedAlerts) 
      });
      setSelectedAlerts(new Set());
      refetch();
    } catch (error) {
      console.error('Failed to bulk acknowledge:', error);
    }
  };

  const toggleSelectAlert = (alertId: string) => {
    const newSelected = new Set(selectedAlerts);
    if (newSelected.has(alertId)) {
      newSelected.delete(alertId);
    } else {
      newSelected.add(alertId);
    }
    setSelectedAlerts(newSelected);
  };

  if (isLoading) {
    return <AlertsSkeleton />;
  }

  return (
    <div className="flex flex-col h-full">
      <Header title="Alerts" />
      
      <div className="flex-1 p-6 space-y-6">
        {/* Filters */}
        <Card>
          <CardHeader>
            <CardTitle>Filters</CardTitle>
          </CardHeader>
          <CardContent>
            <div className="flex flex-wrap gap-4">
              {/* Status Filter */}
              <div className="space-y-2">
                <label className="text-sm font-medium">Status</label>
                <div className="flex gap-2">
                  <Button
                    variant={statusFilter === undefined ? "default" : "outline"}
                    size="sm"
                    onClick={() => setStatusFilter(undefined)}
                  >
                    All
                  </Button>
                  <Button
                    variant={statusFilter === 'open' ? "default" : "outline"}
                    size="sm"
                    onClick={() => setStatusFilter('open')}
                  >
                    Open
                  </Button>
                  <Button
                    variant={statusFilter === 'acknowledged' ? "default" : "outline"}
                    size="sm"
                    onClick={() => setStatusFilter('acknowledged')}
                  >
                    Acknowledged
                  </Button>
                  <Button
                    variant={statusFilter === 'resolved' ? "default" : "outline"}
                    size="sm"
                    onClick={() => setStatusFilter('resolved')}
                  >
                    Resolved
                  </Button>
                </div>
              </div>

              {/* Severity Filter */}
              <div className="space-y-2">
                <label className="text-sm font-medium">Severity</label>
                <div className="flex gap-2">
                  <Button
                    variant={severityFilter === undefined ? "default" : "outline"}
                    size="sm"
                    onClick={() => setSeverityFilter(undefined)}
                  >
                    All
                  </Button>
                  <Button
                    variant={severityFilter === 'critical' ? "default" : "outline"}
                    size="sm"
                    onClick={() => setSeverityFilter('critical')}
                  >
                    Critical
                  </Button>
                  <Button
                    variant={severityFilter === 'high' ? "default" : "outline"}
                    size="sm"
                    onClick={() => setSeverityFilter('high')}
                  >
                    High
                  </Button>
                  <Button
                    variant={severityFilter === 'medium' ? "default" : "outline"}
                    size="sm"
                    onClick={() => setSeverityFilter('medium')}
                  >
                    Medium
                  </Button>
                  <Button
                    variant={severityFilter === 'low' ? "default" : "outline"}
                    size="sm"
                    onClick={() => setSeverityFilter('low')}
                  >
                    Low
                  </Button>
                </div>
              </div>
            </div>
          </CardContent>
        </Card>

        {/* Bulk Actions */}
        {selectedAlerts.size > 0 && (
          <Card className="border-blue-200 bg-blue-50">
            <CardContent className="pt-6">
              <div className="flex items-center justify-between">
                <span className="text-sm font-medium">
                  {selectedAlerts.size} alert{selectedAlerts.size > 1 ? 's' : ''} selected
                </span>
                <div className="flex gap-2">
                  <Button
                    size="sm"
                    onClick={handleBulkAcknowledge}
                    disabled={bulkAcknowledgeMutation.isPending}
                  >
                    <CheckCircle className="h-4 w-4 mr-2" />
                    Acknowledge All
                  </Button>
                  <Button
                    size="sm"
                    variant="outline"
                    onClick={() => setSelectedAlerts(new Set())}
                  >
                    Clear Selection
                  </Button>
                </div>
              </div>
            </CardContent>
          </Card>
        )}

        {/* Alerts Table */}
        <Card>
          <CardHeader>
            <div className="flex items-center justify-between">
              <CardTitle>Alerts ({data?.total || 0})</CardTitle>
              <Badge variant="outline">{alerts.length} shown</Badge>
            </div>
          </CardHeader>
          <CardContent>
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead className="w-12">
                    <input
                      type="checkbox"
                      onChange={(e) => {
                        if (e.target.checked) {
                          setSelectedAlerts(new Set(alerts.filter(a => a.status === 'open').map(a => a.id)));
                        } else {
                          setSelectedAlerts(new Set());
                        }
                      }}
                      checked={selectedAlerts.size > 0 && selectedAlerts.size === alerts.filter(a => a.status === 'open').length}
                    />
                  </TableHead>
                  <TableHead>Severity</TableHead>
                  <TableHead>Agent</TableHead>
                  <TableHead>File Path</TableHead>
                  <TableHead>Type</TableHead>
                  <TableHead>Status</TableHead>
                  <TableHead>Detected</TableHead>
                  <TableHead>Actions</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {alerts.length === 0 ? (
                  <TableRow>
                    <TableCell colSpan={8} className="text-center text-muted-foreground">
                      No alerts found
                    </TableCell>
                  </TableRow>
                ) : (
                  alerts.map((alert) => (
                    <TableRow key={alert.id}>
                      <TableCell>
                        {alert.status === 'open' && (
                          <input
                            type="checkbox"
                            checked={selectedAlerts.has(alert.id)}
                            onChange={() => toggleSelectAlert(alert.id)}
                          />
                        )}
                      </TableCell>
                      <TableCell>
                        <SeverityBadge severity={alert.severity} />
                      </TableCell>
                      <TableCell className="font-medium">{alert.agent_hostname}</TableCell>
                      <TableCell className="max-w-xs truncate" title={alert.file_path}>
                        {alert.file_path}
                      </TableCell>
                      <TableCell>
                        <Badge variant="outline">{alert.alert_type}</Badge>
                      </TableCell>
                      <TableCell>
                        <StatusBadge status={alert.status} />
                      </TableCell>
                      <TableCell className="text-sm text-muted-foreground">
                        {formatRelativeTime(alert.detected_at)}
                      </TableCell>
                      <TableCell>
                        <div className="flex gap-2">
                          {alert.status === 'open' && (
                            <>
                              <Button
                                size="sm"
                                variant="outline"
                                onClick={() => handleAcknowledge(alert.id)}
                                disabled={acknowledgeMutation.isPending}
                              >
                                <CheckCircle className="h-4 w-4" />
                              </Button>
                              <Button
                                size="sm"
                                variant="outline"
                                onClick={() => handleResolve(alert.id)}
                                disabled={resolveMutation.isPending}
                              >
                                <XCircle className="h-4 w-4" />
                              </Button>
                            </>
                          )}
                          {alert.status === 'acknowledged' && (
                            <Button
                              size="sm"
                              variant="outline"
                              onClick={() => handleResolve(alert.id)}
                              disabled={resolveMutation.isPending}
                            >
                              <XCircle className="h-4 w-4 mr-1" />
                              Resolve
                            </Button>
                          )}
                        </div>
                      </TableCell>
                    </TableRow>
                  ))
                )}
              </TableBody>
            </Table>
          </CardContent>
        </Card>
      </div>
    </div>
  );
}

function AlertsSkeleton() {
  return (
    <div className="flex flex-col h-full">
      <Header title="Alerts" />
      <div className="flex-1 p-6 space-y-6">
        <Skeleton className="h-32" />
        <Skeleton className="h-96" />
      </div>
    </div>
  );
}
