'use client';

import { Suspense, useState } from 'react';
import { useSearchParams, useRouter } from 'next/navigation';
import { SummaryPanel } from '@/components/generation/SummaryPanel';
import { FlashcardDeckViewer } from '@/components/generation/FlashcardDeckViewer';
import { useConversationSelection } from '@/components/providers/ConversationSelectionProvider';
import { cn } from '@/lib/utils';
import { Layers, MessageSquare, Sparkles, ArrowLeft } from 'lucide-react';

type IntelligenceTab = 'doc-summary' | 'conv-summary' | 'flashcards';

const TABS: { id: IntelligenceTab; label: string; description: string; icon: typeof Sparkles }[] = [
  { id: 'doc-summary',  label: 'Document Summary',    description: 'AI-generated summary of the active document', icon: Sparkles      },
  { id: 'conv-summary', label: 'Conversation Summary', description: 'Summary of your current conversation',        icon: MessageSquare },
  { id: 'flashcards',   label: 'Flashcards',           description: 'Study cards generated from your content',    icon: Layers        },
];

function IntelligencePage() {
  const router = useRouter();
  const searchParams = useSearchParams();
  const initialTab = (searchParams.get('tab') as IntelligenceTab | null) ?? 'doc-summary';
  const [activeTab, setActiveTab] = useState<IntelligenceTab>(initialTab);

  const { selection } = useConversationSelection();
  const activeDocumentId = selection.documentId ?? undefined;
  const activeConversationId = selection.conversationId ?? undefined;

  const current = TABS.find(t => t.id === activeTab)!;

  return (
    <div className="min-h-screen bg-background text-foreground">
      {/* Header */}
      <div className="sticky top-0 z-10 border-b border-border/50 bg-background/80 backdrop-blur-md">
        <div className="flex items-center gap-3 px-6 h-14">
          <button
            type="button"
            onClick={() => router.back()}
            className="flex items-center gap-1.5 text-sm text-muted-foreground hover:text-foreground transition-colors"
          >
            <ArrowLeft className="w-4 h-4" />
            Back
          </button>
          <span className="text-muted-foreground/40">/</span>
          <span className="text-sm font-semibold text-foreground">Intelligence</span>
        </div>
      </div>

      <div className="max-w-3xl mx-auto px-6 py-8 space-y-6">
        {/* Tab selector */}
        <div className="flex flex-col gap-2">
          {TABS.map(({ id, label, description, icon: Icon }) => (
            <button
              key={id}
              type="button"
              onClick={() => setActiveTab(id)}
              className={cn(
                'flex items-center justify-between rounded-xl border px-4 py-3.5 text-left transition-colors',
                activeTab === id
                  ? 'border-primary/50 bg-primary/[0.06] text-foreground'
                  : 'border-border bg-card hover:border-primary/30 hover:bg-primary/[0.03] text-muted-foreground',
              )}
            >
              <span className="flex items-center gap-3">
                <span className={cn(
                  'flex h-8 w-8 items-center justify-center rounded-lg border',
                  activeTab === id ? 'border-primary/30 bg-primary/10' : 'border-border bg-muted/30',
                )}>
                  <Icon className={cn('h-4 w-4', activeTab === id ? 'text-primary' : 'text-muted-foreground')} />
                </span>
                <span className="flex flex-col gap-0.5">
                  <span className={cn('text-sm font-medium', activeTab === id && 'text-foreground')}>{label}</span>
                  <span className="text-xs text-muted-foreground">{description}</span>
                </span>
              </span>
            </button>
          ))}
        </div>

        {/* Content area */}
        <div className="pt-2">
          <div className="mb-4 flex items-center gap-2">
            <current.icon className="h-4 w-4 text-primary" />
            <h2 className="text-base font-semibold text-foreground">{current.label}</h2>
          </div>

          {activeTab === 'doc-summary' && (
            <SummaryPanel documentId={activeDocumentId} />
          )}
          {activeTab === 'conv-summary' && (
            <SummaryPanel conversationId={activeConversationId} />
          )}
          {activeTab === 'flashcards' && (
            <FlashcardDeckViewer
              documentId={activeDocumentId}
              conversationId={activeConversationId}
            />
          )}

          {/* Context hint when nothing is selected */}
          {activeTab === 'doc-summary' && !activeDocumentId && (
            <p className="mt-4 text-xs text-muted-foreground">
              Open a document from the sidebar to generate a summary.
            </p>
          )}
          {activeTab === 'conv-summary' && !activeConversationId && (
            <p className="mt-4 text-xs text-muted-foreground">
              Start a conversation to generate a summary.
            </p>
          )}
          {activeTab === 'flashcards' && !activeDocumentId && !activeConversationId && (
            <p className="mt-4 text-xs text-muted-foreground">
              Open a document or start a conversation to generate flashcards.
            </p>
          )}
        </div>
      </div>
    </div>
  );
}

export default function IntelligencePageWrapper() {
  return (
    <Suspense>
      <IntelligencePage />
    </Suspense>
  );
}
