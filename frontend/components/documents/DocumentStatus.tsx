'use client';

import { DocumentStatus as StatusType } from '@/lib/types';
import { cn } from '@/lib/utils';
import { CheckCircle, CircleNotch, Warning, Hourglass } from '@phosphor-icons/react';

interface DocumentStatusProps {
  status: StatusType;
}

const STATUS_CONFIG: Record<StatusType, {
  label: string;
  icon: React.ElementType;
  className: string;
}> = {
  processing: {
    label: 'Processing',
    icon: CircleNotch,
    className: 'bg-amber-500/15 text-amber-400 border-amber-500/20',
  },
  indexing: {
    label: 'Indexing',
    icon: Hourglass,
    className: 'bg-blue-500/15 text-blue-400 border-blue-500/20',
  },
  ready: {
    label: 'Ready',
    icon: CheckCircle,
    className: 'bg-green-500/15 text-green-400 border-green-500/20',
  },
  failed: {
    label: 'Failed',
    icon: Warning,
    className: 'bg-red-500/15 text-red-400 border-red-500/20',
  },
  partial: {
    label: 'Partial',
    icon: Warning,
    className: 'bg-orange-500/15 text-orange-400 border-orange-500/20',
  },
};

export function DocumentStatusBadge({ status }: DocumentStatusProps) {
  const config = STATUS_CONFIG[status];
  const Icon = config.icon;
  const isSpinning = status === 'processing' || status === 'indexing';

  return (
    <span className={cn(
      'inline-flex items-center gap-1 text-[10px] font-medium px-1.5 py-0.5 rounded-md border',
      config.className
    )}>
      <Icon className={cn('size-2.5', isSpinning && 'animate-spin')} weight="fill" />
      {config.label}
    </span>
  );
}
