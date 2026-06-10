'use client';

import { useQuery } from '@tanstack/react-query';
import api from '@/lib/api';
import { FlashcardDeck } from '@/lib/types';

interface FlashcardsResponse {
  decks: FlashcardDeck[];
}

interface UseFlashcardsOptions {
  conversation_id?: string;
  document_id?: string;
  deck_id?: string;
  enabled?: boolean;
}

export function useFlashcards({ conversation_id, document_id, deck_id, enabled = true }: UseFlashcardsOptions) {
  const params = new URLSearchParams();
  if (deck_id) params.set('deck_id', deck_id);
  else if (conversation_id) params.set('conversation_id', conversation_id);
  else if (document_id) params.set('document_id', document_id);

  const hasParam = deck_id || conversation_id || document_id;

  return useQuery<FlashcardDeck[]>({
    queryKey: ['flashcards', deck_id ?? null, conversation_id ?? null, document_id ?? null],
    queryFn: async () => {
      const res = await api.get<FlashcardsResponse>(`/api/flashcards?${params}`);
      return res.data.decks;
    },
    enabled: enabled && !!hasParam,
    staleTime: 1000 * 60 * 5,
  });
}
