'use client';

import { useBaselines, useApproveBaseline } from '@/hooks/useBaselines';
import { Header } from '@/components/layout/Header';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table';
import { Skeleton } from '@/components/ui/skeleton';
import { Button } from '@/components/ui/button';
import { Badge } from '@/components/ui/badge';
import { formatDate } from '@/lib/utils/format';
import { Shield, CheckCircle, Clock } from 'lucide-react';

export default function BaselinesPage() {
  const { data, isLoading, refetch } = useBaselines();
  const approveMutation = useApproveBaseline();

  const handleApprove = async (baselineId: string) => {
    const notes = prompt('Approval notes (optional):');
    
    try {
      await approveMutation.mutateAsync({ baseline_id: baselineId, notes: notes || undefined });
      refetch();
    } catch (error) {
      console.error('Failed to approve baseline:', error);
    }
  };

  if (isLoading) {
    return <BaselinesSkeleton />;
  }

  const baselines = data?.baselines || [];
  const activeBaselines = baselines.filter(b => b.is_active);
  const approvedBaselines = baselines.filter(b => b.is_approved);

  return (
    <div className="flex flex-col h-full">
      <Header title="Baselines" />
      
      <div className="flex-1 p-6 space-y-6">
        {/* Summary Cards */}
        <div className="grid gap-4 md:grid-cols-3">
          <Card>
            <CardHeader className="flex flex-row items-center justify-between space-y-0 pb-2">
              <CardTitle className="text-sm font-medium">Total Baselines</CardTitle>
              <Shield className="h-4 w-4 text-muted-foreground" />
            </CardHeader>
            <CardContent>
              <div className="text-2xl font-bold">{data?.total || 0}</div>
            </CardContent>
          </Card>

          <Card>
            <CardHeader className="flex flex-row items-center justify-between space-y-0 pb-2">
              <CardTitle className="text-sm font-medium">Active</CardTitle>
              <CheckCircle className="h-4 w-4 text-green-600" />
            </CardHeader>
            <CardContent>
              <div className="text-2xl font-bold">{activeBaselines.length}</div>
            </CardContent>
          </Card>

          <Card>
            <CardHeader className="flex flex-row items-center justify-between space-y-0 pb-2">
              <CardTitle className="text-sm font-medium">Approved</CardTitle>
              <CheckCircle className="h-4 w-4 text-blue-600" />
            </CardHeader>
            <CardContent>
              <div className="text-2xl font-bold">{approvedBaselines.length}</div>
            </CardContent>
          </Card>
        </div>

        {/* Baselines Table */}
        <Card>
          <CardHeader>
            <CardTitle>Baseline List</CardTitle>
          </CardHeader>
          <CardContent>
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>Name</TableHead>
                  <TableHead>Agent ID</TableHead>
                  <TableHead>File Count</TableHead>
                  <TableHead>Status</TableHead>
                  <TableHead>Approved</TableHead>
                  <TableHead>Created</TableHead>
                  <TableHead>Actions</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {baselines.length === 0 ? (
                  <TableRow>
                    <TableCell colSpan={7} className="text-center text-muted-foreground">
                      No baselines found
                    </TableCell>
                  </TableRow>
                ) : (
                  baselines.map((baseline) => (
                    <TableRow key={baseline.id}>
                      <TableCell className="font-medium">{baseline.baseline_name}</TableCell>
                      <TableCell className="font-mono text-xs">{baseline.agent_id.substring(0, 8)}...</TableCell>
                      <TableCell>{baseline.file_count.toLocaleString()}</TableCell>
                      <TableCell>
                        {baseline.is_active ? (
                          <Badge className="bg-green-100 text-green-800 border-green-200" variant="outline">
                            Active
                          </Badge>
                        ) : (
                          <Badge variant="outline">Inactive</Badge>
                        )}
                      </TableCell>
                      <TableCell>
                        {baseline.is_approved ? (
                          <div className="flex items-center gap-1 text-sm text-green-600">
                            <CheckCircle className="h-4 w-4" />
                            <span>Yes</span>
                          </div>
                        ) : (
                          <div className="flex items-center gap-1 text-sm text-yellow-600">
                            <Clock className="h-4 w-4" />
                            <span>Pending</span>
                          </div>
                        )}
                      </TableCell>
                      <TableCell className="text-sm text-muted-foreground">
                        {formatDate(baseline.created_at)}
                      </TableCell>
                      <TableCell>
                        {!baseline.is_approved && (
                          <Button
                            size="sm"
                            onClick={() => handleApprove(baseline.id)}
                            disabled={approveMutation.isPending}
                          >
                            <CheckCircle className="h-4 w-4 mr-1" />
                            Approve
                          </Button>
                        )}
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

function BaselinesSkeleton() {
  return (
    <div className="flex flex-col h-full">
      <Header title="Baselines" />
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
