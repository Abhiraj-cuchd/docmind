'use client';

import { Conversation } from '@/lib/types';
import { Button } from '@/components/ui/button';
import { Skeleton } from '@/components/ui/skeleton';
import { ScrollArea } from '@/components/ui/scroll-area';
import { Plus, ChatCircle, SignOut } from '@phosphor-icons/react';
import { useAuth } from '@/hooks/useAuth';
import { cn } from '@/lib/utils';
import { formatDistanceToNow } from 'date-fns';

interface ConversationSidebarProps {
  conversations: Conversation[];
  loading: boolean;
  activeId: string | null;
  onSelect: (conversation: Conversation) => void;
  onNew: () => void;
}

export function ConversationSidebar({
  conversations,
  loading,
  activeId,
  onSelect,
  onNew,
}: ConversationSidebarProps) {
  const { signOut } = useAuth();

  return (
    <div className="flex flex-col h-full glass-panel">
      {/* Header */}
      <div className="p-4 border-b border-border/50 flex items-center justify-between">
        <div className="flex items-center gap-2">
          <div className="w-6 h-6 rounded-lg bg-primary/10 border border-primary/20 flex items-center justify-center">
            <svg width="12" height="12" viewBox="0 0 24 24" fill="none" className="text-primary">
              <path d="M12 2L2 7l10 5 10-5-10-5zM2 17l10 5 10-5M2 12l10 5 10-5" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"/>
            </svg>
          </div>
          <span className="text-sm font-bold gradient-text">MindAgent</span>
        </div>

        <div className="flex items-center gap-1" />
      </div>

      {/* New conversation button */}
      <div className="p-3">
        <Button
          id="new-conversation-btn"
          onClick={onNew}
          variant="outline"
          className="w-full justify-start gap-2 text-xs h-8 border-dashed border-border hover:border-primary/40 hover:text-primary transition-all"
        >
          <Plus className="size-3.5" />
          New conversation
        </Button>
      </div>

      {/* Conversation list */}
      <ScrollArea className="flex-1 px-2">
        <div className="space-y-0.5 pb-2">
          {loading ? (
            Array.from({ length: 5 }).map((_, i) => (
              <div key={i} className="p-2 space-y-1.5">
                <Skeleton className="h-3 w-3/4" />
                <Skeleton className="h-2 w-1/2" />
              </div>
            ))
          ) : conversations.length === 0 ? (
            <div className="text-center py-8 px-4">
              <ChatCircle className="size-8 text-muted-foreground/30 mx-auto mb-2" />
              <p className="text-xs text-muted-foreground">No conversations yet</p>
              <p className="text-xs text-muted-foreground/60">Start one above</p>
            </div>
          ) : (
            conversations.map(conv => (
              <button
                key={conv.id}
                onClick={() => onSelect(conv)}
                className={cn(
                  'w-full text-left px-3 py-2.5 rounded-xl transition-all duration-150 group',
                  activeId === conv.id
                    ? 'bg-primary/10 text-foreground border border-primary/20'
                    : 'text-muted-foreground hover:bg-muted/40 hover:text-foreground border border-transparent'
                )}
              >
                <p className="text-xs font-medium truncate">{conv.title}</p>
                <p className="text-[10px] text-muted-foreground/60 mt-0.5">
                  {formatDistanceToNow(new Date(conv.updated_at), { addSuffix: true })}
                </p>
              </button>
            ))
          )}
        </div>
      </ScrollArea>

      {/* Footer */}
      <div className="p-3 border-t border-border/50">
        <button
          onClick={signOut}
          className="w-full flex items-center gap-2 px-3 py-2 rounded-xl text-xs text-muted-foreground hover:text-destructive hover:bg-destructive/10 transition-colors"
        >
          <SignOut className="size-3.5" />
          Sign out
        </button>
      </div>
    </div>
  );
}
