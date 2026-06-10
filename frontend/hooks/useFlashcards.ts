'use client';

import { useCallback, useEffect, useState } from 'react';
import api from '@/lib/api';
import { FlashcardDeck } from '@/lib/types';

interface UseFlashcardsReturn {
  decks: FlashcardDeck[];
  loading: boolean;
  error: string | null;
  refresh: () => void;
}

interface UseFlashcardsOptions {
  conversation_id?: string;
  document_id?: string;
  deck_id?: string;
  enabled?: boolean;
}

export function useFlashcards({
  conversation_id,
  document_id,
  deck_id,
  enabled = true,
}: UseFlashcardsOptions): UseFlashcardsReturn {
  const [decks, setDecks] = useState<FlashcardDeck[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const params = new URLSearchParams();
  if (deck_id) params.set('deck_id', deck_id);
  else if (conversation_id) params.set('conversation_id', conversation_id);
  else if (document_id) params.set('document_id', document_id);
  const hasParam = deck_id || conversation_id || document_id;

  const fetch = useCallback(async () => {
    if (!hasParam) return;
    setLoading(true);
    try {
      const res = await api.get<{ decks: FlashcardDeck[] }>(`/api/flashcards?${params}`);
      setDecks(res.data.decks);
      setError(null);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to load flashcards');
    } finally {
      setLoading(false);
    }
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [deck_id, conversation_id, document_id]);

  useEffect(() => {
    if (enabled && hasParam) {
      fetch();
    }
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [enabled, fetch]);

  return { decks, loading, error, refresh: fetch };
}
