'use client';

import { useState } from 'react';
import { ConversationSidebar } from './ConversationSidebar';
import { ChatWindow } from './ChatWindow';
import { DocumentPanel } from './DocumentPanel';
import { useConversations } from '@/hooks/useConversations';
import { toast } from 'sonner';
import { cn } from '@/lib/utils';

export function ThreePanelLayout() {
  const { conversations, loading, createConversation } = useConversations();
  const [activeConversationId, setActiveConversationId] = useState<string | null>(null);

  const handleNewConversation = async () => {
    const conv = await createConversation('New Conversation');
    if (conv) {
      setActiveConversationId(conv.id);
    } else {
      toast.error('Failed to create conversation');
    }
  };

  return (
    <div className="flex h-screen overflow-hidden bg-background">
      {/* Left panel — 20% — Conversation sidebar */}
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

      {/* Center panel — 50% — Chat window */}
      <main className="flex-1 min-w-0 flex flex-col h-full border-x border-border/50">
        <ChatWindow conversationId={activeConversationId} />
      </main>

      {/* Right panel — 30% — Document viewer */}
      <aside
        className={cn(
          'w-[30%] min-w-[220px] max-w-[380px] h-full flex-shrink-0',
          'hidden lg:flex flex-col'
        )}
      >
        <DocumentPanel />
      </aside>
    </div>
  );
}
