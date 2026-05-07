'use client';

import { useCallback } from 'react';
import { useRouter } from 'next/navigation';
import { DocumentSelectionScreen } from '@/components/layout/DocumentSelectionScreen';
import { useConversationSelection } from '@/components/providers/ConversationSelectionProvider';

export default function DashboardPage() {
  const router = useRouter();
  const { setSelection } = useConversationSelection();

  const handleSelectDocument = useCallback((documentIds: string[]) => {
    setSelection({
      conversationId: null,
      documentId: documentIds[0] ?? null,
      documentIds
    });
    router.push('/chat');
  }, [router, setSelection]);

  return (
    <DocumentSelectionScreen
      onSelect={(documentIds) => void handleSelectDocument(documentIds)}
    />
  );
}



