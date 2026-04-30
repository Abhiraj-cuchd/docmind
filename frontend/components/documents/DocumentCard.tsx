'use client';

import { Document } from '@/lib/types';
import { DocumentStatusBadge } from './DocumentStatus';
import { FilePdf, Rows, Warning } from '@phosphor-icons/react';

interface DocumentCardProps {
  document: Document;
}

export function DocumentCard({ document: doc }: DocumentCardProps) {
  return (
    <div className="flex items-start gap-3 px-3 py-2.5 rounded-xl border border-border/50 bg-card hover:border-border transition-colors">
      <div className="w-8 h-8 rounded-lg bg-red-500/10 border border-red-500/20 flex items-center justify-center shrink-0 mt-0.5">
        <FilePdf className="size-4 text-red-400" weight="fill" />
      </div>

      <div className="flex-1 min-w-0">
        <p className="text-xs font-medium truncate text-foreground" title={doc.filename}>
          {doc.filename}
        </p>

        <div className="flex items-center gap-2 mt-1 flex-wrap">
          <DocumentStatusBadge status={doc.status} />

          {doc.chunk_count !== undefined && doc.status === 'ready' && (
            <span className="flex items-center gap-0.5 text-[10px] text-muted-foreground">
              <Rows className="size-2.5" />
              {doc.chunk_count} chunks
            </span>
          )}
        </div>

        {doc.skipped_pages !== undefined && doc.skipped_pages > 0 && (
          <p className="flex items-center gap-1 text-[10px] text-amber-400 mt-1">
            <Warning className="size-2.5" />
            {doc.skipped_pages} page{doc.skipped_pages > 1 ? 's' : ''} skipped
          </p>
        )}
      </div>
    </div>
  );
}
