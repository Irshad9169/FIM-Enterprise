'use client';

import { Bell, RefreshCw } from 'lucide-react';
import { Button } from '@/components/ui/button';
import { useQueryClient } from '@tanstack/react-query';

interface HeaderProps {
  title: string;
}

export function Header({ title }: HeaderProps) {
  const queryClient = useQueryClient();

  const handleRefresh = () => {
    queryClient.invalidateQueries();
  };

  return (
    <div className="flex h-16 items-center justify-between border-b bg-white px-6">
      <h1 className="text-2xl font-bold">{title}</h1>
      <div className="flex items-center gap-2">
        <Button variant="ghost" size="icon" onClick={handleRefresh}>
          <RefreshCw className="h-5 w-5" />
        </Button>
        <Button variant="ghost" size="icon">
          <Bell className="h-5 w-5" />
        </Button>
      </div>
    </div>
  );
}
