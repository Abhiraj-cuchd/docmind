'use client';

import { useCallback, useEffect, useMemo, useState } from 'react';
import type { ComponentType } from 'react';
import { createClient } from '@/lib/supabase/client';
import { useDocuments } from '@/hooks/useDocuments';
import type { Source } from '@/lib/types';
import PDFViewer, { HighlightTarget } from '@/components/pdf/PDFViewer';
import { Button } from '@/components/ui/button';
import { cn } from '@/lib/utils';
import { ArrowUpRight, Download, FileText, Info, Layers, LayoutGrid, Loader2, MessageSquare, MoreVertical, Sparkles, TriangleAlert, X } from 'lucide-react';
import { getDocColor } from '@/lib/docColors';
import { toast } from 'sonner';
import { SummaryPanel } from '@/components/generation/SummaryPanel';
import { FlashcardDeckViewer } from '@/components/generation/FlashcardDeckViewer';

interface ReferencedDoc {
  id: string;
  filename: string;
}

interface ViewerDocument {
  id: string;
  filename: string;
  status?: string;
}

type IntelligenceTab = 'summary' | 'flashcards' | 'conv-summary';

interface DocumentPanelProps {
  activeDocumentId: string | null;
  activeDocumentIds: string[];
  activeConversationId?: string | null;
  referencedDocs: ReferencedDoc[];
  onDocumentSelect: (documentId: string) => void;
  onClearAll: () => void;
  activeSource?: Source | null;
  onClearActiveSource?: () => void;
  activeHighlight?: HighlightTarget | null;
}

function FooterAction({
  icon: Icon,
  label,
  onClick,
  disabled,
}: {
  icon: ComponentType<{ className?: string }>;
  label: string;
  onClick?: () => void;
  disabled?: boolean;
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      disabled={disabled}
      className="inline-flex h-11 items-center gap-2 rounded-xl border border-white/8 bg-[#0a1220] px-4 text-sm text-white/75 transition-colors hover:bg-white/[0.05] hover:text-white disabled:cursor-not-allowed disabled:opacity-50"
    >
      <Icon className="h-4 w-4" />
      {label}
    </button>
  );
}

export default function DocumentPanel({
  activeDocumentId,
  activeDocumentIds,
  activeConversationId,
  referencedDocs,
  onDocumentSelect,
  onClearAll,
  activeSource,
  onClearActiveSource,
  activeHighlight,
}: DocumentPanelProps) {
  const { documents } = useDocuments();
  const supabase = createClient();
  const [pdfUrl, setPdfUrl] = useState<string | null>(null);
  const [pdfLoading, setPdfLoading] = useState(false);
  const [pdfError, setPdfError] = useState<string | null>(null);
  const [currentPage, setCurrentPage] = useState<number>(activeHighlight?.pageNumber ?? 1);
  const [numPages, setNumPages] = useState<number>(0);
  const [intelligenceOpen, setIntelligenceOpen] = useState(false);
  const [activeTab, setActiveTab] = useState<IntelligenceTab>('summary');

  const viewerDocumentIds = useMemo(
    () => referencedDocs.length > 0
      ? referencedDocs.map(doc => doc.id)
      : activeDocumentIds.length > 0
        ? activeDocumentIds
        : activeDocumentId
          ? [activeDocumentId]
          : [],
    [activeDocumentId, activeDocumentIds, referencedDocs],
  );

  const viewerDocuments = useMemo<ViewerDocument[]>(
    () => viewerDocumentIds.map((documentId) => {
      const doc = documents.find(item => item.id === documentId);
      const fallback = referencedDocs.find(item => item.id === documentId);
      return {
        id: documentId,
        filename: doc?.filename ?? fallback?.filename ?? 'Document.pdf',
        status: doc?.status,
      };
    }),
    [documents, referencedDocs, viewerDocumentIds],
  );

  const resolvedActiveDocumentId =
    activeDocumentId && viewerDocumentIds.includes(activeDocumentId)
      ? activeDocumentId
      : viewerDocumentIds[0] ?? null;
  const activeDocument = viewerDocuments.find(doc => doc.id === resolvedActiveDocumentId) ?? null;
  const highlight = useMemo<HighlightTarget | null>(
    () => activeHighlight ?? (
      activeSource
        ? { content: activeSource.snippet, pageNumber: activeSource.page_number ?? 1 }
        : null
    ),
    [activeHighlight, activeSource],
  );

  useEffect(() => {
    setCurrentPage(highlight?.pageNumber ?? 1);
  }, [highlight?.pageNumber, resolvedActiveDocumentId]);

  useEffect(() => {
    setNumPages(0);
  }, [resolvedActiveDocumentId]);

  useEffect(() => {
    if (!resolvedActiveDocumentId) {
      setPdfUrl(null);
      setPdfError(null);
      return;
    }

    let cancelled = false;

    async function fetchUrl() {
      setPdfLoading(true);
      setPdfUrl(null);
      setPdfError(null);

      try {
        const { data: { session } } = await supabase.auth.getSession();
        if (!session) {
          if (!cancelled) setPdfError('Not authenticated');
          return;
        }

        const res = await fetch(`/api/document-url?document_id=${resolvedActiveDocumentId}`, {
          headers: { Authorization: `Bearer ${session.access_token}` },
        });

        if (!res.ok) {
          const err = await res.json().catch(() => ({}));
          if (!cancelled) setPdfError(err.message || 'Failed to load document');
          return;
        }

        const data = await res.json();
        if (!cancelled) {
          setPdfUrl(data.document_url);
        }
      } catch {
        if (!cancelled) {
          setPdfError('Failed to load document preview');
        }
      } finally {
        if (!cancelled) {
          setPdfLoading(false);
        }
      }
    }

    void fetchUrl();

    return () => {
      cancelled = true;
    };
  }, [resolvedActiveDocumentId, supabase]);

  const handleOpenCurrent = useCallback(() => {
    if (!pdfUrl) return;
    window.open(pdfUrl, '_blank', 'noopener,noreferrer');
  }, [pdfUrl]);

  const handleDownload = useCallback(() => {
    if (!pdfUrl) return;
    const link = document.createElement('a');
    link.href = pdfUrl;
    link.download = activeDocument?.filename ?? 'document.pdf';
    link.target = '_blank';
    link.rel = 'noopener noreferrer';
    link.click();
  }, [activeDocument?.filename, pdfUrl]);

  if (!activeDocument) {
    return (
      <aside className="flex h-full w-full flex-col bg-[#060d18]">
        <div className="border-b border-white/8 px-6 py-3">
          <div className="flex items-center justify-between">
            <div className="flex items-center gap-2 text-white">
              <span className="text-lg font-semibold">Referenced Documents (0)</span>
              <Info className="h-4 w-4 text-white/35" />
            </div>
            <button
              type="button"
              onClick={onClearAll}
              className="text-sm text-white/45 transition-colors hover:text-white"
            >
              Clear all
            </button>
          </div>
        </div>

        <div className="flex flex-1 items-center justify-center px-10 text-center">
          <div className="max-w-sm">
            <div className="mx-auto flex h-16 w-16 items-center justify-center rounded-2xl border border-white/8 bg-white/[0.03]">
              <FileText className="h-7 w-7 text-white/30" />
            </div>
            <p className="mt-5 text-lg font-medium text-white">No document selected</p>
            <p className="mt-2 text-sm text-white/45">
              Pick a document from the library or start a conversation to open the viewer.
            </p>
          </div>
        </div>
      </aside>
    );
  }

  return (
    <aside className="flex h-full w-full flex-col bg-[#060d18] text-white">
      <div className="border-b border-white/8 px-6 py-3">
        <div className="flex items-center justify-between gap-3">
          <div className="flex items-center gap-2">
            <span className="text-lg font-semibold">Referenced Documents ({viewerDocuments.length})</span>
            <Info className="h-4 w-4 text-white/35" />
          </div>
          <button
            type="button"
            onClick={onClearAll}
            className="text-sm text-white/45 transition-colors hover:text-white"
          >
            Clear all
          </button>
        </div>

        <div className="mt-3 flex gap-3 overflow-x-auto pb-1">
          {viewerDocuments.map((doc) => {
            const color = getDocColor(doc.id, viewerDocumentIds);
            const isActive = doc.id === resolvedActiveDocumentId;

            return (
              <button
                key={doc.id}
                type="button"
                onClick={() => onDocumentSelect(doc.id)}
                className={cn(
                  'min-w-[208px] rounded-2xl border px-4 py-2 text-left transition-colors',
                  isActive
                    ? 'border-[#2c5cb8] bg-[#15326e] shadow-[0_8px_24px_rgba(21,50,110,0.32)]'
                    : 'border-white/8 bg-[#09111f] hover:bg-[#0d1830]',
                )}
              >
                <div className="flex items-start gap-3">
                  <div className={cn(
                    'mt-0.5 flex h-7 w-7 shrink-0 items-center justify-center rounded-xl border',
                    isActive ? 'border-white/12 bg-white/10' : `${color.border} ${color.bg}`,
                  )}>
                    <FileText className={cn('h-4 w-4', isActive ? 'text-white' : color.text)} strokeWidth={2.2} />
                  </div>
                  <div className="min-w-0 flex-1">
                    <p className={cn(
                      'truncate text-[15px] font-medium',
                      isActive ? 'text-white' : 'text-slate-100',
                    )}>
                      {doc.filename}
                    </p>
                    <p className={cn(
                      'mt-1 text-xs',
                      isActive ? 'text-blue-100/90' : 'text-white/35',
                    )}>
                      {isActive ? 'Active' : (doc.status === 'ready' ? 'Ready to review' : doc.status ?? 'Available')}
                    </p>
                  </div>
                  {isActive ? <ArrowUpRight className="mt-0.5 h-4 w-4 text-white/70" /> : null}
                </div>
              </button>
            );
          })}
        </div>
      </div>

      <div className="flex items-center justify-between border-b border-white/8 px-6 py-2.5">
        <div className="min-w-0">
          <p className="truncate text-lg font-medium text-white">{activeDocument.filename}</p>
        </div>
        <div className="ml-4 flex items-center gap-3 text-sm text-white/70">
          <span>Page {numPages > 0 ? currentPage : '—'} of {numPages > 0 ? numPages : '—'}</span>
          <div className="flex items-center gap-1">
            <button
              type="button"
              onClick={() => setCurrentPage(page => Math.max(1, page - 1))}
              disabled={currentPage <= 1}
              className="rounded-lg p-1.5 text-white/60 transition-colors hover:bg-white/[0.05] hover:text-white disabled:cursor-not-allowed disabled:opacity-30"
            >
              ‹
            </button>
            <button
              type="button"
              onClick={() => setCurrentPage(page => Math.min(numPages || page, page + 1))}
              disabled={numPages > 0 && currentPage >= numPages}
              className="rounded-lg p-1.5 text-white/60 transition-colors hover:bg-white/[0.05] hover:text-white disabled:cursor-not-allowed disabled:opacity-30"
            >
              ›
            </button>
            <button
              type="button"
              onClick={handleOpenCurrent}
              className="rounded-lg p-1.5 text-white/60 transition-colors hover:bg-white/[0.05] hover:text-white"
            >
              <MoreVertical className="h-4 w-4" />
            </button>
          </div>
        </div>
      </div>

      <div className="min-h-0 flex-1 overflow-hidden bg-[#050c17]">
        {pdfLoading ? (
          <div className="flex h-full flex-col items-center justify-center gap-3 text-white/55">
            <Loader2 className="h-8 w-8 animate-spin text-blue-400" />
            <p className="text-sm">Loading preview...</p>
          </div>
        ) : pdfError ? (
          <div className="flex h-full flex-col items-center justify-center gap-3 px-6 text-center">
            <TriangleAlert className="h-8 w-8 text-amber-400" />
            <p className="text-sm text-white/80">{pdfError}</p>
            <Button
              type="button"
              variant="outline"
              onClick={() => onDocumentSelect(activeDocument.id)}
              className="border-white/12 bg-white/[0.03] text-white hover:bg-white/[0.05]"
            >
              Retry
            </Button>
          </div>
        ) : pdfUrl ? (
          <PDFViewer
            key={activeDocument.id}
            url={pdfUrl}
            currentPage={currentPage}
            onPageChange={setCurrentPage}
            onPageCountChange={setNumPages}
            highlight={highlight}
          />
        ) : null}
      </div>

      {/* Intelligence drawer */}
      {intelligenceOpen && (
        <div className="border-t border-white/8 bg-[#060d18]">
          {/* Tab bar */}
          <div className="flex items-center gap-1 border-b border-white/8 px-4 pt-3 pb-0">
            {([
              { id: 'summary',      label: 'Document Summary', icon: Sparkles },
              { id: 'conv-summary', label: 'Chat Summary',     icon: MessageSquare },
              { id: 'flashcards',   label: 'Flashcards',       icon: Layers },
            ] as { id: IntelligenceTab; label: string; icon: ComponentType<{ className?: string }> }[]).map(({ id, label, icon: Icon }) => (
              <button
                key={id}
                type="button"
                onClick={() => setActiveTab(id)}
                className={cn(
                  'flex items-center gap-1.5 rounded-t-lg border-b-2 px-3 py-2 text-xs font-medium transition-colors',
                  activeTab === id
                    ? 'border-blue-400 text-white'
                    : 'border-transparent text-white/40 hover:text-white/70',
                )}
              >
                <Icon className="h-3.5 w-3.5" />
                {label}
              </button>
            ))}
          </div>

          {/* Tab content */}
          <div className="max-h-64 overflow-y-auto p-4">
            {activeTab === 'summary' && (
              <SummaryPanel documentId={resolvedActiveDocumentId ?? undefined} />
            )}
            {activeTab === 'conv-summary' && (
              <SummaryPanel conversationId={activeConversationId ?? undefined} />
            )}
            {activeTab === 'flashcards' && (
              <FlashcardDeckViewer
                documentId={resolvedActiveDocumentId ?? undefined}
                conversationId={activeConversationId ?? undefined}
              />
            )}
          </div>
        </div>
      )}

      <div className="border-t border-white/8 px-5 py-4">
        <div className="flex flex-wrap items-center gap-3">
          <FooterAction
            icon={Sparkles}
            label="Summarize"
            onClick={() => { setIntelligenceOpen(v => !v); setActiveTab('summary'); }}
          />
          <FooterAction
            icon={MessageSquare}
            label="Chat Summary"
            onClick={() => { setIntelligenceOpen(v => !v); setActiveTab('conv-summary'); }}
            disabled={!activeConversationId}
          />
          <FooterAction
            icon={Layers}
            label="Flashcards"
            onClick={() => { setIntelligenceOpen(v => !v); setActiveTab('flashcards'); }}
          />
          <FooterAction icon={Download} label="Download" onClick={handleDownload} disabled={!pdfUrl} />
          <button
            type="button"
            onClick={() => {
              onClearActiveSource?.();
              handleOpenCurrent();
            }}
            className="ml-auto flex h-11 w-11 items-center justify-center rounded-xl border border-white/8 bg-[#0a1220] text-white/75 transition-colors hover:bg-white/[0.05] hover:text-white"
          >
            <LayoutGrid className="h-4 w-4" />
          </button>
          {intelligenceOpen && (
            <button
              type="button"
              onClick={() => setIntelligenceOpen(false)}
              className="flex h-11 w-11 items-center justify-center rounded-xl border border-white/8 bg-[#0a1220] text-white/50 transition-colors hover:text-white"
            >
              <X className="h-4 w-4" />
            </button>
          )}
        </div>
      </div>
    </aside>
  );
}
