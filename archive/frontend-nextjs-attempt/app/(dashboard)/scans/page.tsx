'use client';

import { useScans } from '@/hooks/useScans';
import { Header } from '@/components/layout/Header';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from '@/components/ui/table';
import { Skeleton } from '@/components/ui/skeleton';
import { Badge } from '@/components/ui/badge';
import { formatDate, formatRelativeTime } from '@/lib/utils/format';
import { FileSearch, CheckCircle, XCircle } from 'lucide-react';

export default function ScansPage() {
  const { data, isLoading } = useScans(undefined, 50);

  if (isLoading) {
    return <ScansSkeleton />;
  }

  const scans = data?.scans || [];
  const completedScans = scans.filter(s => s.status === 'completed');
  const failedScans = scans.filter(s => s.status === 'failed');

  return (
    <div className="flex flex-col h-full">
      <Header title="Scans" />
      
      <div className="flex-1 p-6 space-y-6">
        {/* Summary Cards */}
        <div className="grid gap-4 md:grid-cols-3">
          <Card>
            <CardHeader className="flex flex-row items-center justify-between space-y-0 pb-2">
              <CardTitle className="text-sm font-medium">Total Scans</CardTitle>
              <FileSearch className="h-4 w-4 text-muted-foreground" />
            </CardHeader>
            <CardContent>
              <div className="text-2xl font-bold">{data?.total || 0}</div>
            </CardContent>
          </Card>

          <Card>
            <CardHeader className="flex flex-row items-center justify-between space-y-0 pb-2">
              <CardTitle className="text-sm font-medium">Completed</CardTitle>
              <CheckCircle className="h-4 w-4 text-green-600" />
            </CardHeader>
            <CardContent>
              <div className="text-2xl font-bold">{completedScans.length}</div>
            </CardContent>
          </Card>

          <Card>
            <CardHeader className="flex flex-row items-center justify-between space-y-0 pb-2">
              <CardTitle className="text-sm font-medium">Failed</CardTitle>
              <XCircle className="h-4 w-4 text-red-600" />
            </CardHeader>
            <CardContent>
              <div className="text-2xl font-bold">{failedScans.length}</div>
            </CardContent>
          </Card>
        </div>

        {/* Scans Table */}
        <Card>
          <CardHeader>
            <CardTitle>Scan History</CardTitle>
          </CardHeader>
          <CardContent>
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>Scan ID</TableHead>
                  <TableHead>Agent ID</TableHead>
                  <TableHead>Type</TableHead>
                  <TableHead>Files Scanned</TableHead>
                  <TableHead>Changes</TableHead>
                  <TableHead>Status</TableHead>
                  <TableHead>Started</TableHead>
                  <TableHead>Duration</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {scans.length === 0 ? (
                  <TableRow>
                    <TableCell colSpan={8} className="text-center text-muted-foreground">
                      No scans found
                    </TableCell>
                  </TableRow>
                ) : (
                  scans.map((scan) => (
                    <TableRow key={scan.id}>
                      <TableCell className="font-mono text-xs">
                        {scan.id.substring(0, 8)}...
                      </TableCell>
                      <TableCell className="font-mono text-xs">
                        {scan.agent_id.substring(0, 8)}...
                      </TableCell>
                      <TableCell>
                        <Badge variant="outline">{scan.scan_type}</Badge>
                      </TableCell>
                      <TableCell>{scan.files_scanned.toLocaleString()}</TableCell>
                      <TableCell>
                        {scan.files_changed > 0 ? (
                          <span className="text-orange-600 font-medium">
                            {scan.files_changed}
                          </span>
                        ) : (
                          <span className="text-muted-foreground">0</span>
                        )}
                      </TableCell>
                      <TableCell>
                        {scan.status === 'completed' ? (
                          <Badge className="bg-green-100 text-green-800 border-green-200" variant="outline">
                            Completed
                          </Badge>
                        ) : scan.status === 'failed' ? (
                          <Badge className="bg-red-100 text-red-800 border-red-200" variant="outline">
                            Failed
                          </Badge>
                        ) : (
                          <Badge variant="outline">{scan.status}</Badge>
                        )}
                      </TableCell>
                      <TableCell className="text-sm text-muted-foreground">
                        {formatRelativeTime(scan.started_at)}
                      </TableCell>
                      <TableCell className="text-sm text-muted-foreground">
                        {scan.scan_duration ? `${scan.scan_duration}s` : 'N/A'}
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

function ScansSkeleton() {
  return (
    <div className="flex flex-col h-full">
      <Header title="Scans" />
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
