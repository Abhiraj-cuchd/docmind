'use client';

import { useState, useCallback } from 'react';
import { useDocuments } from '@/hooks/useDocuments';
import { Document } from '@/lib/types';
import { DocumentCard } from '@/components/documents/DocumentCard';
import { UploadZone } from '@/components/documents/UploadZone';
import { Skeleton } from '@/components/ui/skeleton';
import { Button } from '@/components/ui/button';
import {
  Files,
  ArrowLeft,
  ArrowsOut,
  ArrowClockwise,
  FilePdf,
  CircleNotch,
} from '@phosphor-icons/react';
import { getAccessToken } from '@/lib/supabase';
import { toast } from 'sonner';
import { cn } from '@/lib/utils';

type PanelView = 'list' | 'preview';

interface PreviewState {
  docId: string;
  filename: string;
  url: string | null;
  loading: boolean;
  error: string | null;
}

export function DocumentPanel() {
  const { documents, loading, refresh } = useDocuments();
  const [view, setView] = useState<PanelView>('list');
  const [preview, setPreview] = useState<PreviewState | null>(null);

  const openPreview = useCallback(async (doc: Document) => {
    // Only allow previewing ready documents
    if (doc.status !== 'ready') {
      toast.info(`"${doc.filename}" is still ${doc.status}. Please wait until it's ready.`);
      return;
    }

    setPreview({ docId: doc.id, filename: doc.filename, url: null, loading: true, error: null });
    setView('preview');

    try {
      const token = await getAccessToken();
      const res = await fetch(`/api/document-url/${doc.id}`, {
        headers: token ? { Authorization: `Bearer ${token}` } : {},
      });

      if (!res.ok) {
        const err = await res.json().catch(() => ({ error: 'Unknown error' }));
        throw new Error(err.error ?? `HTTP ${res.status}`);
      }

      const data = await res.json();
      // Lambda returns { url: string } or { presigned_url: string }
      const url: string = data.url ?? data.presigned_url ?? data.view_url;
      if (!url) throw new Error('No document URL returned from server');

      setPreview(prev => prev ? { ...prev, url, loading: false } : prev);
    } catch (err) {
      const msg = err instanceof Error ? err.message : 'Failed to load document';
      setPreview(prev => prev ? { ...prev, loading: false, error: msg } : prev);
      toast.error(msg);
    }
  }, []);

  const handleBack = () => {
    setView('list');
    setPreview(null);
  };

  const handleRefreshPreview = () => {
    if (!preview) return;
    const doc = documents.find(d => d.id === preview.docId);
    if (doc) openPreview(doc);
  };

  return (
    <div className="flex flex-col h-full glass-panel border-l border-border/50 border-r-0">
      {/* ── Header ── */}
      <div className="px-4 py-3 border-b border-border/50 flex items-center gap-2 shrink-0">
        {view === 'preview' ? (
          <>
            <button
              onClick={handleBack}
              className="text-muted-foreground hover:text-foreground transition-colors"
              title="Back to list"
            >
              <ArrowLeft className="size-4" />
            </button>
            <FilePdf className="size-4 text-red-400 shrink-0" weight="fill" />
            <h2 className="text-sm font-medium truncate flex-1" title={preview?.filename}>
              {preview?.filename}
            </h2>
            <button
              onClick={handleRefreshPreview}
              className="text-muted-foreground hover:text-foreground transition-colors shrink-0"
              title="Reload document"
            >
              <ArrowClockwise className="size-3.5" />
            </button>
          </>
        ) : (
          <>
            <Files className="size-4 text-muted-foreground" />
            <h2 className="text-sm font-medium">Documents</h2>
            <span className="ml-auto text-[10px] text-muted-foreground/60">
              {documents.length} file{documents.length !== 1 ? 's' : ''}
            </span>
          </>
        )}
      </div>

      {/* ── Upload zone (only in list view) ── */}
      {view === 'list' && (
        <div className="px-3 py-3 border-b border-border/50 shrink-0">
          <UploadZone compact onUploadComplete={refresh} />
        </div>
      )}

      {/* ── Content ── */}
      <div className="flex-1 min-h-0 flex flex-col">
        {view === 'list' ? (
          /* Document list */
          <div className="flex-1 overflow-y-auto px-3 py-3">
            {loading ? (
              <div className="space-y-2">
                {Array.from({ length: 3 }).map((_, i) => (
                  <div key={i} className="flex gap-3 p-2.5">
                    <Skeleton className="w-8 h-8 rounded-lg" />
                    <div className="flex-1 space-y-1.5">
                      <Skeleton className="h-3 w-full" />
                      <Skeleton className="h-2 w-16" />
                    </div>
                  </div>
                ))}
              </div>
            ) : documents.length === 0 ? (
              <div className="text-center py-8">
                <Files className="size-8 text-muted-foreground/20 mx-auto mb-2" />
                <p className="text-xs text-muted-foreground">No documents yet</p>
                <p className="text-xs text-muted-foreground/60">Upload a PDF to get started</p>
              </div>
            ) : (
              <div className="space-y-2">
                {documents.map(doc => (
                  <button
                    key={doc.id}
                    className="w-full text-left group"
                    onClick={() => openPreview(doc)}
                    title={doc.status === 'ready' ? `Preview ${doc.filename}` : `${doc.filename} (${doc.status})`}
                  >
                    <div className={cn(
                      'rounded-xl border transition-all duration-150',
                      doc.status === 'ready'
                        ? 'hover:border-primary/40 hover:shadow-sm hover:shadow-primary/5 cursor-pointer'
                        : 'cursor-not-allowed opacity-70'
                    )}>
                      <DocumentCard document={doc} />
                    </div>
                  </button>
                ))}
              </div>
            )}

            {/* Hint */}
            {!loading && documents.some(d => d.status === 'ready') && (
              <p className="text-[10px] text-muted-foreground/40 text-center mt-4">
                Click a document to preview it
              </p>
            )}
          </div>
        ) : (
          /* PDF preview */
          <div className="flex-1 min-h-0 flex flex-col">
            {preview?.loading ? (
              /* Loading state */
              <div className="flex-1 flex flex-col items-center justify-center gap-3 text-muted-foreground">
                <CircleNotch className="size-8 animate-spin text-primary/60" />
                <p className="text-xs">Loading document…</p>
              </div>
            ) : preview?.error ? (
              /* Error state */
              <div className="flex-1 flex flex-col items-center justify-center gap-3 px-6 text-center">
                <div className="w-10 h-10 rounded-xl bg-destructive/10 border border-destructive/20 flex items-center justify-center">
                  <FilePdf className="size-5 text-destructive" />
                </div>
                <p className="text-xs text-muted-foreground">{preview.error}</p>
                <Button
                  size="sm"
                  variant="outline"
                  onClick={handleRefreshPreview}
                  className="text-xs gap-1.5"
                >
                  <ArrowClockwise className="size-3" />
                  Retry
                </Button>
              </div>
            ) : preview?.url ? (
              /* PDF iframe */
              <iframe
                src={preview.url}
                className="flex-1 w-full border-0 bg-white"
                title={preview.filename}
                sandbox="allow-scripts allow-same-origin"
              />
            ) : null}
          </div>
        )}
      </div>
    </div>
  );
}
