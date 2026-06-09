'use client';

import { useState } from 'react';
import { useAgentSearch } from '@/hooks/useAgentsEnhanced';
import { Input } from '@/components/ui/input';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Search, Loader2, Clock, CheckCircle, AlertCircle } from 'lucide-react';
import { formatRelativeTime } from '@/lib/utils/format';
import { ScanNowButton } from './ScanNowButton';

export function AgentSearch() {
  const [query, setQuery] = useState('');
  const { data, isLoading } = useAgentSearch(query, query.length >= 2);

  return (
    <Card>
      <CardHeader>
        <CardTitle>Search Agents</CardTitle>
      </CardHeader>
      <CardContent className="space-y-4">
        {/* Search Input */}
        <div className="relative">
          <Search className="absolute left-3 top-3 h-4 w-4 text-muted-foreground" />
          <Input
            placeholder="Search by hostname (FQDN)..."
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            className="pl-10"
          />
          {isLoading && (
            <Loader2 className="absolute right-3 top-3 h-4 w-4 animate-spin text-muted-foreground" />
          )}
        </div>

        {/* Results */}
        {query.length >= 2 && data && (
          <div className="space-y-2">
            <p className="text-sm text-muted-foreground">
              Found {data.count} agent{data.count !== 1 ? 's' : ''}
            </p>

            {data.results.length === 0 ? (
              <div className="text-center py-8 text-muted-foreground">
                No agents found matching &quot;{query}&quot;
              </div>
            ) : (
              data.results.map((agent) => (
                <Card key={agent.id} className="border">
                  <CardContent className="p-4">
                    <div className="flex items-start justify-between">
                      {/* Agent Info */}
                      <div className="flex-1">
                        <div className="flex items-center gap-2">
                          <h4 className="font-medium">{agent.hostname}</h4>
                          {agent.status === 'online' ? (
                            <Badge className="bg-green-100 text-green-800 border-green-200" variant="outline">
                              Online
                            </Badge>
                          ) : (
                            <Badge variant="outline">Offline</Badge>
                          )}
                        </div>

                        {/* Scan Status */}
                        <div className="mt-2 space-y-1">
                          {agent.last_scan_at ? (
                            <div className="flex items-center gap-2 text-sm">
                              <Clock className="h-4 w-4 text-muted-foreground" />
                              <span className="text-muted-foreground">
                                Last scanned: {formatRelativeTime(agent.last_scan_at)}
                              </span>
                              {agent.scan_needed ? (
                                <Badge className="bg-yellow-100 text-yellow-800 border-yellow-200" variant="outline">
                                  <AlertCircle className="h-3 w-3 mr-1" />
                                  Scan Needed
                                </Badge>
                              ) : (
                                <Badge className="bg-green-100 text-green-800 border-green-200" variant="outline">
                                  <CheckCircle className="h-3 w-3 mr-1" />
                                  Up to Date
                                </Badge>
                              )}
                            </div>
                          ) : (
                            <div className="flex items-center gap-2 text-sm text-muted-foreground">
                              <AlertCircle className="h-4 w-4" />
                              Never scanned
                            </div>
                          )}

                          {agent.ip_address && (
                            <p className="text-sm text-muted-foreground">
                              IP: {agent.ip_address}
                            </p>
                          )}
                        </div>
                      </div>

                      {/* Scan Now Button */}
                      <div>
                        <ScanNowButton
                          agentId={agent.id}
                          agentHostname={agent.hostname}
                          scanNeeded={agent.scan_needed}
                          hoursSinceScan={agent.hours_since_scan}
                        />
                      </div>
                    </div>
                  </CardContent>
                </Card>
              ))
            )}
          </div>
        )}

        {query.length > 0 && query.length < 2 && (
          <p className="text-sm text-muted-foreground">
            Type at least 2 characters to search
          </p>
        )}
      </CardContent>
    </Card>
  );
}
