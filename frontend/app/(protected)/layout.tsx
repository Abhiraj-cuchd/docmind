'use client';

import { useCallback, useEffect, useState } from 'react';
import { usePathname, useRouter } from 'next/navigation';
import { useAuth } from '@/hooks/useAuth';
import { ConversationSidebar } from '@/components/layout/ConversationSidebar';
import { ConversationSelectionProvider, useConversationSelection } from '@/components/providers/ConversationSelectionProvider';
import { Conversation } from '@/lib/types';
import { Menu, X } from 'lucide-react';

export default function ProtectedLayout({ children }: { children: React.ReactNode }) {
  const { user, loading } = useAuth();
  const router = useRouter();

  useEffect(() => {
    if (!loading && !user) {
      router.replace('/');
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
  const pathname = usePathname();
  const { conversations, conversationsLoading: loading, selection, setSelection, clearSelection, deleteConversation } = useConversationSelection();
  const [sidebarOpen, setSidebarOpen] = useState(false);
  const isChatRoute = pathname === '/chat';

  useEffect(() => {
    if (isChatRoute) {
      setSidebarOpen(false);
    }
  }, [isChatRoute, selection.conversationId]);

  const handleSelectConversation = useCallback((conversation: Conversation) => {
    setSelection({
      conversationId: conversation.id,
      documentId: conversation.document_id ?? conversation.documentIds?.[0] ?? null,
      documentIds: conversation.documentIds ?? (conversation.document_id ? [conversation.document_id] : []),
    });
    setSidebarOpen(false);
    router.push('/chat');
  }, [router, setSelection]);

  const handleNewConversation = useCallback(() => {
    clearSelection();
    setSidebarOpen(false);
    router.push('/chat');
  }, [clearSelection, router]);

  const handleDeleteActive = useCallback(() => {
    clearSelection();
    router.push('/chat');
  }, [clearSelection, router]);

  const handleSelectDocument = useCallback((documentId: string) => {
    setSelection({
      conversationId: null,
      documentId,
      documentIds: [documentId],
    });
    setSidebarOpen(false);
    router.push('/chat');
  }, [router, setSelection]);

  const sidebar = (
    <ConversationSidebar
      conversations={conversations}
      loading={loading}
      activeId={selection.conversationId}
      activeDocumentId={selection.documentId}
      onSelect={handleSelectConversation}
      onSelectDocument={handleSelectDocument}
      onNew={handleNewConversation}
      onDelete={deleteConversation}
      onDeleteActive={handleDeleteActive}
    />
  );

  return (
    <div className="flex h-screen overflow-hidden bg-[#060b14] text-foreground">
      {!isChatRoute && (
        <aside className="h-full w-[330px] min-w-[330px] flex-shrink-0 border-r border-white/8 bg-[#050b16]">
          {sidebar}
        </aside>
      )}

      {isChatRoute && (
        <>
          <button
            type="button"
            onClick={() => setSidebarOpen(true)}
            className="fixed left-4 top-4 z-40 flex h-10 w-10 items-center justify-center rounded-xl border border-white/10 bg-[#07101d]/95 text-white shadow-[0_12px_30px_rgba(0,0,0,0.35)] backdrop-blur transition-colors hover:bg-[#0d1830]"
            aria-label="Open conversations"
            title="Open conversations"
          >
            <Menu className="h-5 w-5" />
          </button>

          {sidebarOpen && (
            <div className="fixed inset-0 z-50">
              <button
                type="button"
                className="absolute inset-0 bg-black/55 backdrop-blur-[2px]"
                onClick={() => setSidebarOpen(false)}
                aria-label="Close conversations overlay"
              />
              <aside className="relative h-full w-[352px] max-w-[88vw] border-r border-white/8 bg-[#050b16] shadow-[24px_0_70px_rgba(0,0,0,0.55)]">
                <button
                  type="button"
                  onClick={() => setSidebarOpen(false)}
                  className="absolute right-3 top-3 z-10 flex h-8 w-8 items-center justify-center rounded-lg text-white/55 transition-colors hover:bg-white/[0.06] hover:text-white"
                  aria-label="Close conversations"
                  title="Close conversations"
                >
                  <X className="h-4 w-4" />
                </button>
                {sidebar}
              </aside>
            </div>
          )}
        </>
      )}

      <main className="h-full min-w-0 flex-1">
        {children}
      </main>
    </div>
  );
}
