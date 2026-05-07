'use client';

import { useMemo, useState } from 'react';
import { Conversation } from '@/lib/types';
import { Button } from '@/components/ui/button';
import { Skeleton } from '@/components/ui/skeleton';
import { ScrollArea } from '@/components/ui/scroll-area';
import { Plus, ChatCircle, SignOut, Trash, Check, X } from '@phosphor-icons/react';
import { useAuth } from '@/hooks/useAuth';
import { useDocuments } from '@/hooks/useDocuments';
import { cn } from '@/lib/utils';
import { formatDistanceToNow } from 'date-fns';
import { toast } from 'sonner';
import { BrainCircuit, ChevronUp, FileText, PlusCircle } from 'lucide-react';
import { DOC_COLORS } from '@/lib/docColors';

interface ConversationSidebarProps {
  conversations: Conversation[];
  loading: boolean;
  activeId: string | null;
  activeDocumentId: string | null;
  onSelect: (conversation: Conversation) => void;
  onSelectDocument: (documentId: string) => void;
  onNew: () => void;
  onDelete: (id: string) => Promise<boolean>;
  onDeleteActive?: () => void;
}

export function ConversationSidebar({
  conversations,
  loading,
  activeId,
  activeDocumentId,
  onSelect,
  onSelectDocument,
  onNew,
  onDelete,
  onDeleteActive,
}: ConversationSidebarProps) {
  const { signOut, user } = useAuth();
  const { documents, loading: documentsLoading } = useDocuments();
  const [confirmingId, setConfirmingId] = useState<string | null>(null);
  const [deletingId, setDeletingId] = useState<string | null>(null);
  const [documentsCollapsed, setDocumentsCollapsed] = useState(false);
  const displayName =
    (user?.user_metadata?.full_name as string | undefined) ??
    (user?.user_metadata?.name as string | undefined) ??
    user?.email?.split('@')[0] ??
    'User';
  const initials = useMemo(() => (
    displayName
      .split(/\s+/)
      .filter(Boolean)
      .slice(0, 2)
      .map(part => part[0]?.toUpperCase() ?? '')
      .join('') || 'U'
  ), [displayName]);

  const handleDeleteClick = (e: React.MouseEvent, id: string) => {
    e.stopPropagation();
    setConfirmingId(id);
  };

  const handleConfirmDelete = async (e: React.MouseEvent, id: string) => {
    e.stopPropagation();
    setConfirmingId(null);
    setDeletingId(id);
    const ok = await onDelete(id);
    setDeletingId(null);
    if (ok) {
      if (id === activeId) onDeleteActive?.();
      toast.success('Conversation deleted');
    } else {
      toast.error('Failed to delete conversation');
    }
  };

  const handleCancelDelete = (e: React.MouseEvent) => {
    e.stopPropagation();
    setConfirmingId(null);
  };

  return (
    <div className="flex h-full flex-col bg-[#050b16] text-slate-100">
      <div className="flex items-center gap-3 px-5 py-5">
        <div className="flex h-8 w-8 items-center justify-center rounded-full bg-[#2563eb] shadow-[0_0_0_1px_rgba(96,165,250,0.24)]">
          <div className="flex h-6 w-6 items-center justify-center rounded-full bg-[#1d4ed8] text-white">
            <BrainCircuit className="h-3.5 w-3.5" strokeWidth={2.1} />
          </div>
        </div>
        <span className="text-[15px] font-semibold tracking-tight text-white">MindAgent</span>
      </div>

      <div className="px-5 pb-4">
        <Button
          id="new-conversation-btn"
          onClick={onNew}
          className="h-10 w-full justify-center gap-2 rounded-xl border-0 bg-[#2563eb] text-sm font-medium text-white shadow-[0_10px_30px_rgba(37,99,235,0.28)] hover:bg-[#1d4ed8]"
        >
          <Plus className="size-4" />
          New conversation
        </Button>
      </div>

      <div className="flex min-h-0 flex-1 flex-col px-4 pb-4">
        <section
          className={cn(
            'flex min-h-0 flex-col border-b border-white/8 pb-3 transition-[height]',
            documentsCollapsed ? 'flex-1' : 'h-[48%]',
          )}
        >
          <div className="shrink-0 px-1 pb-3 text-[13px] font-medium text-white">Conversations</div>
          <ScrollArea className="min-h-0 flex-1 pr-1">
            {loading ? (
              <div className="space-y-3 px-1">
                {Array.from({ length: 5 }).map((_, i) => (
                  <div key={i} className="space-y-2 rounded-xl px-3 py-3">
                    <Skeleton className="h-4 w-4/5 bg-white/8" />
                    <Skeleton className="h-3 w-1/2 bg-white/6" />
                  </div>
                ))}
              </div>
            ) : conversations.length === 0 ? (
              <div className="px-4 py-10 text-center">
                <ChatCircle className="mx-auto mb-3 size-8 text-white/20" />
                <p className="text-sm text-white/70">No conversations yet</p>
                <p className="mt-1 text-xs text-white/35">Start one above</p>
              </div>
            ) : (
              <div className="space-y-1.5">
                {conversations.map(conv => {
                  const isActive = activeId === conv.id;
                  const isConfirming = confirmingId === conv.id;
                  const isDeleting = deletingId === conv.id;

                  return (
                    <div
                      key={conv.id}
                      className={cn(
                        'group flex items-start gap-2 rounded-xl border px-3 py-3 transition-colors',
                        isActive
                          ? 'border-[#2954a3] bg-[#102857]'
                          : 'border-transparent bg-transparent hover:bg-white/[0.04]',
                        isDeleting && 'pointer-events-none opacity-50',
                      )}
                    >
                      <button
                        onClick={() => onSelect(conv)}
                        className="min-w-0 flex-1 text-left"
                      >
                        <p className={cn(
                          'max-w-full truncate text-[15px] font-medium',
                          isActive ? 'text-white' : 'text-slate-100',
                        )}>
                          {conv.title}
                        </p>
                        <p className="mt-1 text-xs text-white/45">
                          {formatDistanceToNow(new Date(conv.updated_at), { addSuffix: true })}
                        </p>
                      </button>

                      {isConfirming ? (
                        <div className="mt-0.5 flex shrink-0 items-center gap-0.5">
                          <button
                            onClick={(e) => handleConfirmDelete(e, conv.id)}
                            className="flex h-7 w-7 items-center justify-center rounded-md text-emerald-300 hover:bg-emerald-500/10"
                            title="Confirm delete"
                          >
                            <Check className="size-3" weight="bold" />
                          </button>
                          <button
                            onClick={handleCancelDelete}
                            className="flex h-7 w-7 items-center justify-center rounded-md text-white/45 hover:bg-white/6 hover:text-white/80"
                            title="Cancel"
                          >
                            <X className="size-3" weight="bold" />
                          </button>
                        </div>
                      ) : (
                        <button
                          onClick={(e) => handleDeleteClick(e, conv.id)}
                          className="mt-0.5 flex h-7 w-7 shrink-0 items-center justify-center rounded-md text-white/35 transition-colors hover:bg-red-500/10 hover:text-red-300"
                          title="Delete conversation"
                        >
                          <Trash className="size-3" />
                        </button>
                      )}
                    </div>
                  );
                })}
              </div>
            )}
          </ScrollArea>
        </section>

        <section
          className={cn(
            'flex min-h-0 flex-col pt-4 transition-[height]',
            documentsCollapsed ? 'h-12 shrink-0' : 'h-[52%]',
          )}
        >
          <button
            type="button"
            onClick={() => setDocumentsCollapsed(prev => !prev)}
            className="flex shrink-0 items-center justify-between rounded-xl border border-white/10 bg-white/[0.05] px-3 py-2 text-left text-[13px] font-semibold text-white shadow-[0_6px_16px_rgba(2,6,23,0.4)] transition-colors hover:bg-white/[0.08]"
            aria-expanded={!documentsCollapsed}
          >
            <span className="flex items-center gap-2">
              <span className="flex h-6 w-6 items-center justify-center rounded-md bg-white/10">
                <FileText className="h-3.5 w-3.5 text-white/80" />
              </span>
              <span>Document Library</span>
            </span>
            <span className="flex items-center gap-2 text-[11px] font-medium text-white/60">
              {documentsCollapsed ? 'Expand' : 'Collapse'}
              <ChevronUp
                className={cn(
                  'h-4 w-4 text-white/60 transition-transform',
                  documentsCollapsed && 'rotate-180',
                )}
              />
            </span>
          </button>
          {!documentsCollapsed && (
          <ScrollArea className="min-h-0 flex-1 pr-1">
            {documentsLoading ? (
              <div className="space-y-3 px-1">
                {Array.from({ length: 4 }).map((_, i) => (
                  <div key={i} className="flex items-center gap-3 rounded-xl px-2 py-2.5">
                    <Skeleton className="h-5 w-5 rounded bg-white/8" />
                    <div className="min-w-0 flex-1 space-y-2">
                      <Skeleton className="h-3.5 w-4/5 bg-white/8" />
                      <Skeleton className="h-3 w-2/5 bg-white/6" />
                    </div>
                  </div>
                ))}
              </div>
            ) : (
              <div className="space-y-0.5">
                {documents.map((doc, index) => {
                  const color = DOC_COLORS[index % DOC_COLORS.length];
                  const isActive = activeDocumentId === doc.id;
                  return (
                    <button
                      key={doc.id}
                      onClick={() => onSelectDocument(doc.id)}
                      className={cn(
                        'flex w-full items-start gap-3 rounded-xl px-3 py-2.5 text-left transition-colors',
                        isActive ? 'bg-white/[0.06]' : 'hover:bg-white/[0.04]',
                      )}
                    >
                      <div className={cn(
                        'mt-0.5 flex h-5 w-5 shrink-0 items-center justify-center rounded-md border',
                        color.bg,
                        color.border,
                      )}>
                        <FileText className={cn('h-3.5 w-3.5', color.text)} strokeWidth={2.2} />
                      </div>
                      <div className="min-w-0 flex-1">
                        <p className={cn(
                          'truncate text-[14px]',
                          isActive ? 'text-white' : 'text-slate-200',
                        )}>
                          {doc.filename}
                        </p>
                        <p className="mt-1 text-[11px] text-white/35">
                          {doc.status === 'ready' ? 'Ready' : doc.status}
                        </p>
                      </div>
                    </button>
                  );
                })}
              </div>
            )}

            <a
              href="/upload"
              className="mt-3 flex items-center gap-2 rounded-xl px-3 py-2.5 text-sm text-white/70 transition-colors hover:bg-white/[0.04] hover:text-white"
            >
              <PlusCircle className="h-4 w-4" />
              Add documents
            </a>
          </ScrollArea>
          )}
        </section>
      </div>

      <div className="border-t border-white/8 px-4 py-4">
        <div className="flex items-center gap-3 rounded-xl px-3 py-2.5 text-left text-white/85">
          <div className="flex h-9 w-9 items-center justify-center rounded-full bg-[#0f4cbf] text-sm font-semibold text-white">
            {initials}
          </div>
          <div className="min-w-0 flex-1">
            <p className="truncate text-[15px] font-medium text-white">{displayName}</p>
            <p className="truncate text-xs text-white/35">{user?.email ?? 'Signed in'}</p>
          </div>
          <ChevronUp className="h-4 w-4 text-white/35" />
        </div>

        <button
          onClick={signOut}
          className="mt-2 flex w-full items-center gap-2 rounded-xl px-3 py-2.5 text-sm text-white/65 transition-colors hover:bg-white/[0.04] hover:text-white"
        >
          <SignOut className="size-4" />
          Sign out
        </button>
      </div>
    </div>
  );
}
