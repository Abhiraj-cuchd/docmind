'use client';

import { useCallback, useRef, useState } from 'react';
import { ConversationSidebar } from './ConversationSidebar';
import { ChatWindow } from './ChatWindow';
import DocumentPanel from './DocumentPanel';
import { DocumentSelectionScreen } from './DocumentSelectionScreen';
import { useConversations } from '@/hooks/useConversations';
import { useAuth } from '@/hooks/useAuth';
import { toast } from 'sonner';
import { cn } from '@/lib/utils';

export function ThreePanelLayout() {
  const { conversations, loading, createConversation } = useConversations();
  const { user } = useAuth();
  const [activeConversationId, setActiveConversationId] = useState<string | null>(null);
  const [activeDocumentId, setActiveDocumentId] = useState<string | null>(null);
  const conversationByDocumentIdRef = useRef<Record<string, string>>({});
  const conversationPromiseByDocumentIdRef = useRef<Record<string, Promise<string | null>>>({});
  const latestSelectedDocumentIdRef = useRef<string | null>(null);

  const handleNewConversation = async () => {
    const conv = await createConversation('New Conversation');
    if (conv) {
      setActiveConversationId(conv.id);
    } else {
      toast.error('Failed to create conversation');
    }
  };

  const handleSelectDocument = useCallback(async (documentId: string, filename?: string) => {
    if (documentId === activeDocumentId && activeConversationId) return;

    latestSelectedDocumentIdRef.current = documentId;
    setActiveDocumentId(documentId);
    
    const existingConversationId = conversationByDocumentIdRef.current[documentId];
    if (existingConversationId) {
      setActiveConversationId(existingConversationId);
      return;
    }

    const existingPromise = conversationPromiseByDocumentIdRef.current[documentId];
    if (existingPromise) {
      setActiveConversationId(null);
      const convId = await existingPromise;
      if (convId && latestSelectedDocumentIdRef.current === documentId) {
        setActiveConversationId(convId);
      }
      return;
    }

    setActiveConversationId(null);

    const rawTitle = (filename ?? 'New Conversation').trim();
    const title = rawTitle.length > 0 ? rawTitle : 'New Conversation';

    const createPromise = (async () => {
      const conv = await createConversation(title, documentId);
      return conv?.id ?? null;
    })();

    conversationPromiseByDocumentIdRef.current[documentId] = createPromise;
    const convId = await createPromise;
    delete conversationPromiseByDocumentIdRef.current[documentId];

    if (convId) {
      conversationByDocumentIdRef.current[documentId] = convId;
      if (latestSelectedDocumentIdRef.current === documentId) {
        setActiveConversationId(convId);
      }
    } else {
      toast.error('Failed to create conversation');
    }
  }, [activeConversationId, activeDocumentId, createConversation]);

  // Landing state: no document selected yet
  if (!activeDocumentId) {
    return (
      <DocumentSelectionScreen
        onSelect={(documentId, filename) => {
          void handleSelectDocument(documentId, filename);
        }}
      />
    );
  }

  return (
    <div className="flex h-screen overflow-hidden bg-background animate-in fade-in-0 duration-300">
      {/* Left panel — conversations */}
      <aside
        className={cn(
          'w-[20%] min-w-[200px] max-w-[280px] h-full flex-shrink-0',
          'hidden md:flex flex-col'
        )}
      >
        <ConversationSidebar
          conversations={conversations}
          loading={loading}
          activeId={activeConversationId}
          onSelect={setActiveConversationId}
          onNew={handleNewConversation}
        />
      </aside>

      {/* Center panel — chat */}
      <main className="flex-1 min-w-0 flex flex-col h-full border-x border-border/50">
        <ChatWindow conversationId={activeConversationId} />
      </main>

      {/* Right panel — document viewer */}
      <aside
        className={cn(
          'w-[40%] min-w-[260px] max-w-[560px] h-full flex-shrink-0',
          'hidden lg:flex flex-col'
        )}
      >
        <DocumentPanel
          userId={user?.id ?? ''}
          activeDocumentId={activeDocumentId}
          onDocumentSelect={(documentId, filename) => {
            void handleSelectDocument(documentId, filename);
          }}
        />
      </aside>
    </div>
  );
}
