'use client';

import { useMemo } from 'react';
import { ChunkEvidence, Source } from '@/lib/types';
import { ArrowSquareOut } from '@phosphor-icons/react';
import { getDocColor } from '@/lib/docColors';
import { cn } from '@/lib/utils';

interface CitationsProps {
  sources: Source[];
  retrievedChunks?: ChunkEvidence[];
  documentIds?: string[];
  onSourceClick?: (source: Source) => void;
  onEvidenceClick?: (evidence: ChunkEvidence) => void;
}

export function Citations({
  sources,
  retrievedChunks,
  documentIds,
  onSourceClick,
  onEvidenceClick,
}: CitationsProps) {
  const colorDocIds = useMemo(() => {
    if (documentIds && documentIds.length > 0) return documentIds;
    const seen = new Set<string>();
    sources.forEach(s => { if (s.document_id) seen.add(s.document_id); });
    return Array.from(seen);
  }, [documentIds, sources]);

  if (!sources.length) return null;

  function handleRowClick(s: Source) {
    const chunk = retrievedChunks?.find(c => c.id === s.chunk_id);
    if (chunk && onEvidenceClick) {
      onEvidenceClick(chunk);
    } else {
      onSourceClick?.(s);
    }
  }

  return (
    <div className="mt-4 rounded-xl border border-white/8 bg-[#0d1626] p-4">
      <p className="mb-3 text-[15px] font-semibold text-white">
        Evidence used ({sources.length})
      </p>

      <div className="overflow-hidden rounded-xl border border-white/8">
        {sources.map((s, i) => {
          const { bg, text, border } = getDocColor(s.document_id, colorDocIds);
          return (
            <div
              key={s.chunk_id ?? `${s.document_id ?? 'doc'}-${i}`}
              onClick={() => handleRowClick(s)}
              role="button"
              tabIndex={0}
              onKeyDown={e => { if (e.key === 'Enter' || e.key === ' ') handleRowClick(s); }}
              aria-label={`View ${s.filename}${s.page_number ? `, page ${s.page_number}` : ''}`}
              className={cn(
                'flex cursor-pointer items-center gap-4 px-4 py-3 transition-colors',
                'hover:bg-white/[0.04] active:bg-white/[0.06]',
                i < sources.length - 1 && 'border-b border-white/8',
              )}
            >
              <span className="w-4 shrink-0 text-center text-[15px] tabular-nums text-white/70">
                {i + 1}
              </span>

              <span
                className={cn(
                  'max-w-[210px] shrink-0 truncate rounded-md border px-2 py-1 text-[15px] font-medium',
                  bg, text, border,
                )}
                title={s.filename}
              >
                {s.filename}
              </span>

              <span className="w-16 shrink-0 text-[15px] tabular-nums text-white/65">
                {s.page_number != null ? `Page ${s.page_number}` : '-'}
              </span>

              <span className="min-w-0 flex-1 truncate text-[15px] text-white/55">
                {s.section ?? '-'}
              </span>

              <ArrowSquareOut
                className="size-4 shrink-0 text-white/45"
                aria-hidden
              />
            </div>
          );
        })}
      </div>
    </div>
  );
}
