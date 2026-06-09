'use client';

import { useState } from 'react';
import { useTriggerScan } from '@/hooks/useAgentsEnhanced';
import { Button } from '@/components/ui/button';
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog';
import { Alert, AlertDescription } from '@/components/ui/alert';
import { Play, Loader2, CheckCircle, AlertCircle } from 'lucide-react';

interface ScanNowButtonProps {
  agentId: string;
  agentHostname: string;
  scanNeeded: boolean;
  hoursSinceScan: number | null;
}

export function ScanNowButton({
  agentId,
  agentHostname,
  scanNeeded,
  hoursSinceScan,
}: ScanNowButtonProps) {
  const [showDialog, setShowDialog] = useState(false);
  const triggerScan = useTriggerScan();

  const handleTrigger = async () => {
    try {
      await triggerScan.mutateAsync(agentId);
      // Keep dialog open to show success
      setTimeout(() => {
        setShowDialog(false);
        triggerScan.reset();
      }, 3000);
    } catch (error) {
      // Error will be shown in the dialog
    }
  };

  const isDisabled = !scanNeeded || triggerScan.isPending || triggerScan.isSuccess;

  return (
    <>
      <Button
        size="sm"
        onClick={() => setShowDialog(true)}
        disabled={isDisabled}
        variant={scanNeeded ? "default" : "outline"}
      >
        <Play className="h-4 w-4 mr-1" />
        Scan Now
      </Button>

      <Dialog open={showDialog} onOpenChange={setShowDialog}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>Trigger Manual Scan</DialogTitle>
            <DialogDescription>
              Request an immediate scan for {agentHostname}
            </DialogDescription>
          </DialogHeader>

          <div className="space-y-4 py-4">
            {/* Status Messages */}
            {triggerScan.isSuccess && (
              <Alert className="border-green-200 bg-green-50">
                <CheckCircle className="h-4 w-4 text-green-600" />
                <AlertDescription className="text-green-800">
                  Scan request created successfully! The agent will execute the scan on its next heartbeat.
                </AlertDescription>
              </Alert>
            )}

            {triggerScan.isError && (
              <Alert variant="destructive">
                <AlertCircle className="h-4 w-4" />
                <AlertDescription>
                  {(triggerScan.error as any)?.response?.data?.detail ||
                    'Failed to trigger scan. Please try again.'}
                </AlertDescription>
              </Alert>
            )}

            {!triggerScan.isSuccess && !triggerScan.isError && (
              <div className="space-y-2">
                <p className="text-sm">
                  <strong>Agent:</strong> {agentHostname}
                </p>
                {hoursSinceScan !== null && (
                  <p className="text-sm text-muted-foreground">
                    Last scanned: {hoursSinceScan.toFixed(1)} hours ago
                  </p>
                )}
                <p className="text-sm text-muted-foreground">
                  The agent will be notified to perform a scan on its next check-in.
                </p>
              </div>
            )}
          </div>

          <DialogFooter>
            {triggerScan.isSuccess ? (
              <Button onClick={() => setShowDialog(false)}>Close</Button>
            ) : (
              <>
                <Button variant="outline" onClick={() => setShowDialog(false)}>
                  Cancel
                </Button>
                <Button
                  onClick={handleTrigger}
                  disabled={triggerScan.isPending}
                >
                  {triggerScan.isPending && <Loader2 className="mr-2 h-4 w-4 animate-spin" />}
                  Confirm Scan
                </Button>
              </>
            )}
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </>
  );
}
