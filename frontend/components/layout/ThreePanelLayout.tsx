'use client';

import { useCallback, useRef } from 'react';
import { ChatWindow } from './ChatWindow';
import DocumentPanel from './DocumentPanel';
import { useConversations } from '@/hooks/useConversations';
import { useAuth } from '@/hooks/useAuth';

interface ThreePanelLayoutProps {
  activeConversationId: string | null;
  activeDocumentId: string | null;
  setSelection: (selection: { conversationId: string | null; documentId: string | null }) => void;
  updateSelection: (selection: { conversationId?: string | null; documentId?: string | null }) => void;
  onBack: () => void;
}

export function ThreePanelLayout({
  activeConversationId,
  activeDocumentId,
  setSelection,
  updateSelection,
  onBack,
}: ThreePanelLayoutProps) {
  const { createConversation } = useConversations();
  const { user } = useAuth();
  const conversationByDocumentIdRef = useRef<Record<string, string>>({});
  const handleSelectDocument = useCallback((documentId: string) => {
    if (documentId === activeDocumentId) {
      // Same document clicked — start a new conversation on it
      setSelection({ conversationId: null, documentId });
      return;
    }

    const cachedConversationId = conversationByDocumentIdRef.current[documentId];
    if (cachedConversationId) {
      setSelection({ conversationId: cachedConversationId, documentId });
      return;
    }

    setSelection({ conversationId: null, documentId });
  }, [activeDocumentId, setSelection]);

  return (
    <div className="flex h-full overflow-hidden bg-background animate-in fade-in-0 duration-300">
      {/* Center panel — chat */}
      <main className="flex-1 min-w-0 flex flex-col h-full border-x border-border/50">
        <ChatWindow
          conversationId={activeConversationId}
          documentId={activeDocumentId}
          createConversation={createConversation}
          onConversationCreated={(convId) => {
            if (activeDocumentId) {
              conversationByDocumentIdRef.current[activeDocumentId] = convId;
            }
            updateSelection({ conversationId: convId });
          }}
          onBack={onBack}
        />
      </main>

      {/* Right panel — document viewer */}
      <aside className="w-[40%] min-w-[260px] max-w-[560px] h-full flex-shrink-0 hidden lg:flex flex-col">
        <DocumentPanel
          userId={user?.id ?? ''}
          activeDocumentId={activeDocumentId}
          onDocumentSelect={(documentId) => {
            void handleSelectDocument(documentId);
          }}
        />
      </aside>
    </div>
  );
}
