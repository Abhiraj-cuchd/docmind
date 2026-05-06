'use client';

import { createContext, useCallback, useContext, useMemo, useState } from 'react';
import { useConversations } from '@/hooks/useConversations';
import { Conversation } from '@/lib/types';

interface ConversationSelectionState {
  conversationId: string | null;
  documentId: string | null;
}

interface ConversationSelectionContextValue {
  selection: ConversationSelectionState;
  setSelection: (selection: ConversationSelectionState) => void;
  updateSelection: (partial: Partial<ConversationSelectionState>) => void;
  clearSelection: () => void;
  conversations: Conversation[];
  conversationsLoading: boolean;
  createConversation: (title?: string, documentId?: string) => Promise<Conversation | null>;
  deleteConversation: (id: string) => Promise<boolean>;
}

const ConversationSelectionContext = createContext<ConversationSelectionContextValue | null>(null);

export function ConversationSelectionProvider({ children }: { children: React.ReactNode }) {
  const [selection, setSelectionState] = useState<ConversationSelectionState>({
    conversationId: null,
    documentId: null,
  });

  const { conversations, loading: conversationsLoading, createConversation, deleteConversation } = useConversations();

  const setSelection = useCallback((next: ConversationSelectionState) => {
    setSelectionState(next);
  }, []);

  const updateSelection = useCallback((partial: Partial<ConversationSelectionState>) => {
    setSelectionState(prev => ({ ...prev, ...partial }));
  }, []);

  const clearSelection = useCallback(() => {
    setSelectionState({ conversationId: null, documentId: null });
  }, []);

  const value = useMemo(
    () => ({
      selection,
      setSelection,
      updateSelection,
      clearSelection,
      conversations,
      conversationsLoading,
      createConversation,
      deleteConversation,
    }),
    [selection, setSelection, updateSelection, clearSelection, conversations, conversationsLoading, createConversation, deleteConversation]
  );

  return (
    <ConversationSelectionContext.Provider value={value}>
      {children}
    </ConversationSelectionContext.Provider>
  );
}

export function useConversationSelection() {
  const context = useContext(ConversationSelectionContext);
  if (!context) {
    throw new Error('useConversationSelection must be used within ConversationSelectionProvider');
  }
  return context;
}
