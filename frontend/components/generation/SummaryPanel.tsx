'use client';

import { useState } from 'react';
import { useSummaries } from '@/hooks/useSummaries';
import { useGenerate } from '@/hooks/useGenerate';
import { useQueryClient } from '@tanstack/react-query';
import { Button } from '@/components/ui/button';
import { Skeleton } from '@/components/ui/skeleton';
import { cn } from '@/lib/utils';
import { toast } from 'sonner';
import { ChevronDown, ChevronUp, RefreshCw, Sparkles } from 'lucide-react';

interface SummaryPanelProps {
  conversationId?: string;
  documentId?: string;
}

export function SummaryPanel({ conversationId, documentId }: SummaryPanelProps) {
  const [expanded, setExpanded] = useState(false);
  const queryClient = useQueryClient();

  const { data: summaries, isLoading: isFetching } = useSummaries({
    conversation_id: conversationId,
    document_id: documentId,
  });

  const { generate, isLoading, isPolling } = useGenerate();

  const summary = summaries?.[0] ?? null;
  const isBusy = isLoading || isPolling;

  async function handleGenerate() {
    try {
      const taskType = conversationId ? 'summarize_conversation' : 'summarize_document';
      const result = await generate({
        task_type: taskType,
        conversation_id: conversationId,
        document_id: documentId,
      });

      if (result?.status === 'done') {
        await queryClient.invalidateQueries({
          queryKey: ['summaries', conversationId ?? null, documentId ?? null],
        });
        setExpanded(true);
        toast.success('Summary generated');
      } else if (result?.status === 'error') {
        toast.error(result.message ?? 'Summary generation failed');
      }
    } catch {
      toast.error('Summary generation failed');
    }
  }

  return (
    <div className="rounded-xl border border-white/8 bg-[#0a1220] overflow-hidden">
      {/* Header */}
      <div className="flex items-center justify-between px-4 py-3">
        <div className="flex items-center gap-2">
          <Sparkles className="h-4 w-4 text-primary/70" />
          <span className="text-sm font-medium text-white/80">Summary</span>
          {summary && (
            <span className="text-xs text-white/30">
              {new Date(summary.created_at).toLocaleDateString()}
            </span>
          )}
        </div>

        <div className="flex items-center gap-2">
          <Button
            variant="ghost"
            size="icon-sm"
            onClick={handleGenerate}
            disabled={isBusy}
            title={summary ? 'Regenerate summary' : 'Generate summary'}
          >
            <RefreshCw className={cn('h-3.5 w-3.5 text-white/50', isBusy && 'animate-spin')} />
          </Button>

          {summary && (
            <Button
              variant="ghost"
              size="icon-sm"
              onClick={() => setExpanded(v => !v)}
            >
              {expanded
                ? <ChevronUp className="h-3.5 w-3.5 text-white/50" />
                : <ChevronDown className="h-3.5 w-3.5 text-white/50" />
              }
            </Button>
          )}
        </div>
      </div>

      {/* Body */}
      {isFetching && (
        <div className="px-4 pb-4 space-y-2">
          <Skeleton className="h-3 w-full bg-white/5" />
          <Skeleton className="h-3 w-4/5 bg-white/5" />
          <Skeleton className="h-3 w-3/5 bg-white/5" />
        </div>
      )}

      {isBusy && !isFetching && (
        <div className="px-4 pb-4">
          <div className="flex items-center gap-2 text-xs text-white/40">
            <RefreshCw className="h-3 w-3 animate-spin" />
            {isPolling ? 'Generating summary…' : 'Starting…'}
          </div>
        </div>
      )}

      {!isFetching && !isBusy && !summary && (
        <div className="px-4 pb-4">
          <p className="text-xs text-white/30">No summary yet — click the refresh button to generate one.</p>
        </div>
      )}

      {!isFetching && !isBusy && summary && expanded && (
        <div className="px-4 pb-4 border-t border-white/5 pt-3">
          <p className="text-sm text-white/70 leading-relaxed whitespace-pre-wrap">
            {summary.content}
          </p>
        </div>
      )}

      {!isFetching && !isBusy && summary && !expanded && (
        <div
          className="px-4 pb-3 cursor-pointer"
          onClick={() => setExpanded(true)}
        >
          <p className="text-xs text-white/40 line-clamp-2 leading-relaxed">
            {summary.content}
          </p>
        </div>
      )}
    </div>
  );
}
