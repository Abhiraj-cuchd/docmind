'use client';

import { useCallback } from 'react';
import { useRouter } from 'next/navigation';
import { DocumentSelectionScreen } from '@/components/layout/DocumentSelectionScreen';
import { useConversations } from '@/hooks/useConversations';
import { useConversationSelection } from '@/components/providers/ConversationSelectionProvider';

export default function DashboardPage() {
  const router = useRouter();
  const { conversations } = useConversations();
  const { setSelection } = useConversationSelection();

  const handleSelectDocument = useCallback(async (documentId: string) => {
    const existingConversation = conversations.find(conv => conv.document_id === documentId);
    if (existingConversation) {
      setSelection({ conversationId: existingConversation.id, documentId });
      router.push('/chat');
      return;
    }

    setSelection({ conversationId: null, documentId });
    router.push('/chat');
  }, [conversations, router, setSelection]);

  return (
    <DocumentSelectionScreen
      onSelect={(documentId) => {
        void handleSelectDocument(documentId);
      }}
    />
  );
}



