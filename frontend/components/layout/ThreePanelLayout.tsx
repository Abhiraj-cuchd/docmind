'use client';

import { useCallback, useRef, useState } from 'react';
import { ChatWindow } from './ChatWindow';
import DocumentPanel from './DocumentPanel';
import { useConversationSelection } from '@/components/providers/ConversationSelectionProvider';
import { useAuth } from '@/hooks/useAuth';
import { Source } from '@/lib/types';

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
  const { createConversation } = useConversationSelection();
  const { user } = useAuth();
  const conversationByDocumentIdRef = useRef<Record<string, string>>({});
  const [activeSource, setActiveSource] = useState<Source | null>(null);

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

  const handleSourceClick = useCallback((source: Source) => {
    if (source.document_id && source.document_id !== activeDocumentId) {
      handleSelectDocument(source.document_id);
    }
    setActiveSource(source);
  }, [activeDocumentId, handleSelectDocument]);

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
          onSourceClick={handleSourceClick}
        />
      </main>

      {/* Right panel — document viewer */}
      <aside className="w-[46%] min-w-[280px] max-w-[640px] h-full flex-shrink-0 hidden lg:flex flex-col">
        <DocumentPanel
          userId={user?.id ?? ''}
          activeDocumentId={activeDocumentId}
          onDocumentSelect={(documentId) => {
            void handleSelectDocument(documentId);
          }}
          onDocumentDeleted={(documentId) => {
            if (documentId === activeDocumentId) {
              setSelection({ conversationId: null, documentId: null });
            }
          }}
          activeSource={activeSource}
          onClearActiveSource={() => setActiveSource(null)}
        />
      </aside>
    </div>
  );
}
