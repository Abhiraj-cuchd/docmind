'use client';

import { useCallback, useEffect } from 'react';
import { useRouter } from 'next/navigation';
import { useAuth } from '@/hooks/useAuth';
import { ConversationSidebar } from '@/components/layout/ConversationSidebar';
import { ConversationSelectionProvider, useConversationSelection } from '@/components/providers/ConversationSelectionProvider';
import { Conversation } from '@/lib/types';

export default function ProtectedLayout({ children }: { children: React.ReactNode }) {
  const { user, loading } = useAuth();
  const router = useRouter();

  useEffect(() => {
    if (!loading && !user) {
      router.replace('/login');
    }
  }, [user, loading, router]);

  if (loading) {
    return (
      <div className="min-h-screen flex items-center justify-center bg-background">
        <div className="flex flex-col items-center gap-3">
          <div className="w-8 h-8 rounded-full border-2 border-primary border-t-transparent animate-spin" />
          <p className="text-muted-foreground text-sm">Loading…</p>
        </div>
      </div>
    );
  }

  if (!user) return null;

  return (
    <ConversationSelectionProvider>
      <ProtectedShell>{children}</ProtectedShell>
    </ConversationSelectionProvider>
  );
}

function ProtectedShell({ children }: { children: React.ReactNode }) {
  const router = useRouter();
  const { conversations, conversationsLoading: loading, selection, setSelection, clearSelection, deleteConversation } = useConversationSelection();

  const handleSelectConversation = useCallback((conversation: Conversation) => {
    setSelection({
      conversationId: conversation.id,
      documentId: conversation.document_id ?? null,
    });
    router.push('/chat');
  }, [router, setSelection]);

  const handleNewConversation = useCallback(() => {
    clearSelection();
    router.push('/dashboard');
  }, [clearSelection, router]);

  const handleDeleteActive = useCallback(() => {
    clearSelection();
    router.push('/dashboard');
  }, [clearSelection, router]);

  return (
    <div className="flex h-screen overflow-hidden bg-background">
      <aside className="w-[20%] min-w-[200px] max-w-[280px] h-full flex-shrink-0">
        <ConversationSidebar
          conversations={conversations}
          loading={loading}
          activeId={selection.conversationId}
          onSelect={handleSelectConversation}
          onNew={handleNewConversation}
          onDelete={deleteConversation}
          onDeleteActive={handleDeleteActive}
        />
      </aside>
      <main className="flex-1 min-w-0 h-full">
        {children}
      </main>
    </div>
  );
}
