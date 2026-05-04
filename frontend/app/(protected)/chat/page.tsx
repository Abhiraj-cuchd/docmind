'use client';

import { useRouter } from 'next/navigation';
import { ThreePanelLayout } from '@/components/layout/ThreePanelLayout';
import { useConversationSelection } from '@/components/providers/ConversationSelectionProvider';


export default function ChatPage() {
  const router = useRouter();
  const { selection, setSelection, updateSelection, clearSelection } = useConversationSelection();

  return (
    <ThreePanelLayout
      activeConversationId={selection.conversationId}
      activeDocumentId={selection.documentId}
      setSelection={setSelection}
      updateSelection={updateSelection}
      onBack={() => {
        clearSelection();
        router.push('/dashboard');
      }}
    />
  );
}
