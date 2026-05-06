'use client';

import { Source } from '@/lib/types';
import { FileText } from '@phosphor-icons/react';

interface CitationsProps {
  sources: Source[];
  onSourceClick?: (source: Source) => void;
}

export function Citations({ sources, onSourceClick }: CitationsProps) {
  if (!sources.length) return null;

  return (
    <div className="mt-3 pt-3 border-t border-border/50">
      <p className="text-xs text-muted-foreground mb-2 font-medium uppercase tracking-wide">Sources</p>
      <div className="flex flex-wrap gap-2">
        {sources.map((s) => (
          <button
            key={s.chunk_id ?? `${s.document_id ?? 'doc'}-${s.page_number ?? 'na'}-${s.filename}`}
            onClick={() => onSourceClick?.(s)}
            className="inline-flex items-center gap-1.5 bg-muted/50 border border-border/50 rounded-lg px-2.5 py-1.5 text-xs text-muted-foreground hover:text-foreground transition-colors"
          >
            <FileText className="size-3 shrink-0 text-primary/70" />
            <span className="truncate max-w-[160px]">
              {s.page_number ? `Page ${s.page_number}` : s.filename}
            </span>
            {s.section && <span className="text-muted-foreground/60 shrink-0">· {s.section}</span>}
          </button>
        ))}
      </div>
    </div>
  );
}
