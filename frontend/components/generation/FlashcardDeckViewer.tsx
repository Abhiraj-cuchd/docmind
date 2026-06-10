'use client';

import { useState } from 'react';
import { useFlashcards } from '@/hooks/useFlashcards';
import { useGenerate } from '@/hooks/useGenerate';
import { useQueryClient } from '@tanstack/react-query';
import { Flashcard } from '@/lib/types';
import { Button } from '@/components/ui/button';
import { Skeleton } from '@/components/ui/skeleton';
import { cn } from '@/lib/utils';
import { toast } from 'sonner';
import { ChevronLeft, ChevronRight, RotateCcw, Layers, RefreshCw } from 'lucide-react';

interface FlashcardDeckViewerProps {
  conversationId?: string;
  documentId?: string;
}

function FlipCard({ card }: { card: Flashcard }) {
  const [flipped, setFlipped] = useState(false);

  return (
    <div
      className="relative h-44 cursor-pointer select-none"
      style={{ perspective: '1000px' }}
      onClick={() => setFlipped(v => !v)}
    >
      <div
        className="relative w-full h-full transition-transform duration-500"
        style={{
          transformStyle: 'preserve-3d',
          transform: flipped ? 'rotateY(180deg)' : 'rotateY(0deg)',
        }}
      >
        {/* Front — question */}
        <div
          className="absolute inset-0 rounded-xl border border-white/10 bg-white/[0.04] flex flex-col items-center justify-center p-5 gap-3"
          style={{ backfaceVisibility: 'hidden' }}
        >
          <span className="text-xs text-white/30 uppercase tracking-wider">Question</span>
          <p className="text-sm text-white/85 text-center leading-relaxed">{card.question}</p>
          <span className="text-xs text-white/20 mt-auto">Tap to reveal answer</span>
        </div>

        {/* Back — answer */}
        <div
          className="absolute inset-0 rounded-xl border border-primary/20 bg-primary/5 flex flex-col items-center justify-center p-5 gap-3"
          style={{ backfaceVisibility: 'hidden', transform: 'rotateY(180deg)' }}
        >
          <span className="text-xs text-primary/60 uppercase tracking-wider">Answer</span>
          <p className="text-sm text-white/85 text-center leading-relaxed">{card.answer}</p>
        </div>
      </div>
    </div>
  );
}

export function FlashcardDeckViewer({ conversationId, documentId }: FlashcardDeckViewerProps) {
  const [cardIndex, setCardIndex] = useState(0);
  const queryClient = useQueryClient();

  const { data: decks, isLoading: isFetching } = useFlashcards({
    conversation_id: conversationId,
    document_id: documentId,
  });

  const { generate, isLoading, isPolling } = useGenerate();

  const deck  = decks?.[0] ?? null;
  const cards = deck?.cards ?? [];
  const isBusy = isLoading || isPolling;

  function prev() { setCardIndex(i => Math.max(0, i - 1)); }
  function next() { setCardIndex(i => Math.min(cards.length - 1, i + 1)); }

  async function handleGenerate() {
    try {
      const result = await generate({
        task_type: 'generate_flashcards',
        conversation_id: conversationId,
        document_id: documentId,
      });

      if (result?.status === 'done') {
        await queryClient.invalidateQueries({
          queryKey: ['flashcards', null, conversationId ?? null, documentId ?? null],
        });
        setCardIndex(0);
        toast.success(`${result.count ?? 0} flashcards generated`);
      } else if (result?.status === 'error') {
        toast.error(result.message ?? 'Flashcard generation failed');
      }
    } catch {
      toast.error('Flashcard generation failed');
    }
  }

  return (
    <div className="rounded-xl border border-white/8 bg-[#0a1220] overflow-hidden">
      {/* Header */}
      <div className="flex items-center justify-between px-4 py-3">
        <div className="flex items-center gap-2">
          <Layers className="h-4 w-4 text-primary/70" />
          <span className="text-sm font-medium text-white/80">Flashcards</span>
          {cards.length > 0 && (
            <span className="text-xs text-white/30">{cards.length} cards</span>
          )}
        </div>

        <Button
          variant="ghost"
          size="icon-sm"
          onClick={handleGenerate}
          disabled={isBusy}
          title={deck ? 'Regenerate flashcards' : 'Generate flashcards'}
        >
          <RefreshCw className={cn('h-3.5 w-3.5 text-white/50', isBusy && 'animate-spin')} />
        </Button>
      </div>

      {/* Body */}
      {isFetching && (
        <div className="px-4 pb-4 space-y-2">
          <Skeleton className="h-44 w-full bg-white/5 rounded-xl" />
        </div>
      )}

      {isBusy && !isFetching && (
        <div className="px-4 pb-4 h-44 flex items-center justify-center">
          <div className="flex items-center gap-2 text-xs text-white/40">
            <RefreshCw className="h-3 w-3 animate-spin" />
            {isPolling ? 'Generating flashcards…' : 'Starting…'}
          </div>
        </div>
      )}

      {!isFetching && !isBusy && cards.length === 0 && (
        <div className="px-4 pb-4 h-20 flex items-center">
          <p className="text-xs text-white/30">No flashcards yet — click the refresh button to generate.</p>
        </div>
      )}

      {!isFetching && !isBusy && cards.length > 0 && (
        <div className="px-4 pb-4 space-y-3">
          <FlipCard card={cards[cardIndex]} />

          {/* Navigation */}
          <div className="flex items-center justify-between">
            <Button
              variant="ghost"
              size="icon-sm"
              onClick={prev}
              disabled={cardIndex === 0}
            >
              <ChevronLeft className="h-4 w-4 text-white/50" />
            </Button>

            <span className="text-xs text-white/30">
              {cardIndex + 1} / {cards.length}
            </span>

            <Button
              variant="ghost"
              size="icon-sm"
              onClick={next}
              disabled={cardIndex === cards.length - 1}
            >
              <ChevronRight className="h-4 w-4 text-white/50" />
            </Button>
          </div>

          <button
            type="button"
            onClick={() => setCardIndex(0)}
            className="flex items-center gap-1.5 text-xs text-white/25 hover:text-white/50 transition-colors"
          >
            <RotateCcw className="h-3 w-3" />
            Restart deck
          </button>
        </div>
      )}
    </div>
  );
}
