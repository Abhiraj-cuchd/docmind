'use client'

import { useState, useEffect, useCallback, useRef } from 'react'
import { createClient } from '@/lib/supabase/client'
import {
  FileText, Upload, AlertCircle,
  CheckCircle, Loader2,
  ExternalLink, RefreshCw, ArrowLeft
} from 'lucide-react'
import { Button } from '@/components/ui/button'
import { ScrollArea } from '@/components/ui/scroll-area'
import {
  Tooltip,
  TooltipContent,
  TooltipProvider,
  TooltipTrigger
} from '@/components/ui/tooltip'

// ─────────────────────────────────────────────────────────────────────
// TYPES
// ─────────────────────────────────────────────────────────────────────

interface Document {
  id: string
  filename: string
  status: 'processing' | 'indexing' | 'ready' | 'failed'
  chunk_count: number | null
  created_at: string
  skipped_pages: { page_number: number; reason: string }[]
  doc_metadata: {
    total_pages?: number
    extracted_pages?: number
    file_size_bytes?: number
  } | null
}

interface DocumentPanelProps {
  userId: string
  activeDocumentId: string | null
  onDocumentSelect: (documentId: string, filename?: string) => void
}

// ─────────────────────────────────────────────────────────────────────
// HELPERS
// ─────────────────────────────────────────────────────────────────────

function formatBytes(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`
}

function formatDate(dateStr: string): string {
  return new Date(dateStr).toLocaleDateString('en-IN', {
    day:   '2-digit',
    month: 'short',
    year:  'numeric',
  })
}

function StatusBadge({ status }: { status: Document['status'] }) {
  const config = {
    processing: { label: 'Processing', icon: Loader2,      cls: 'bg-yellow-500/20 text-yellow-400 border-yellow-500/30', spin: true  },
    indexing:   { label: 'Indexing',   icon: Loader2,      cls: 'bg-blue-500/20 text-blue-400 border-blue-500/30',       spin: true  },
    ready:      { label: 'Ready',      icon: CheckCircle,  cls: 'bg-green-500/20 text-green-400 border-green-500/30',    spin: false },
    failed:     { label: 'Failed',     icon: AlertCircle,  cls: 'bg-red-500/20 text-red-400 border-red-500/30',          spin: false },
  }

  const { label, icon: Icon, cls, spin } = config[status]

  return (
    <span className={`inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-xs border ${cls}`}>
      <Icon className={`w-3 h-3 ${spin ? 'animate-spin' : ''}`} />
      {label}
    </span>
  )
}

// ─────────────────────────────────────────────────────────────────────
// DOCUMENT CARD
// ─────────────────────────────────────────────────────────────────────

interface DocumentCardProps {
  document: Document
  isActive: boolean
  onSelect: () => void
}

function DocumentCard({ document, isActive, onSelect }: DocumentCardProps) {
  const totalPages   = document.doc_metadata?.total_pages
  const fileSize     = document.doc_metadata?.file_size_bytes
  const skippedCount = document.skipped_pages?.length ?? 0
  const isReady      = document.status === 'ready'
  const isProcessing = ['processing', 'indexing'].includes(document.status)

  return (
    <div
      className={`
        flex flex-col gap-2 p-3 rounded-lg border cursor-pointer
        transition-all duration-150
        ${isActive
          ? 'border-blue-500/50 bg-blue-500/10'
          : 'border-zinc-700/50 bg-zinc-800/30 hover:border-zinc-600 hover:bg-zinc-800/60'
        }
      `}
      onClick={onSelect}
    >
      {/* Top row */}
      <div className="flex items-start justify-between gap-2">
        <div className="flex items-start gap-2 min-w-0">
          <FileText className={`w-4 h-4 mt-0.5 shrink-0 ${isActive ? 'text-blue-400' : 'text-zinc-400'}`} />
          <div className="min-w-0">
            <p className="text-sm font-medium text-zinc-100 truncate leading-tight">
              {document.filename}
            </p>
            <p className="text-xs text-zinc-500 mt-0.5">
              {formatDate(document.created_at)}
            </p>
          </div>
        </div>
        <StatusBadge status={document.status} />
      </div>

      {/* Meta row */}
      {isReady && (
        <div className="flex items-center gap-3 text-xs text-zinc-500">
          {document.chunk_count && (
            <span>{document.chunk_count.toLocaleString()} chunks</span>
          )}
          {totalPages && <span>{totalPages} pages</span>}
          {fileSize && <span>{formatBytes(fileSize)}</span>}
        </div>
      )}

      {/* Skipped pages warning */}
      {skippedCount > 0 && (
        <div className="flex items-center gap-1.5 text-xs text-yellow-500/80">
          <AlertCircle className="w-3 h-3 shrink-0" />
          <span>{skippedCount} page{skippedCount > 1 ? 's' : ''} skipped (images only)</span>
        </div>
      )}

      {/* Processing indicator */}
      {isProcessing && (
        <div className="flex items-center gap-1.5 text-xs text-blue-400/80">
          <Loader2 className="w-3 h-3 animate-spin shrink-0" />
          <span>
            {document.status === 'processing' ? 'Extracting text...' : 'Generating embeddings...'}
          </span>
        </div>
      )}

      {/* Click hint for ready docs */}
      {isReady && !isActive && (
        <p className="text-[10px] text-zinc-600">Click to preview</p>
      )}
    </div>
  )
}

// ─────────────────────────────────────────────────────────────────────
// MAIN DOCUMENT PANEL
// ─────────────────────────────────────────────────────────────────────

export default function DocumentPanel({
  userId,
  activeDocumentId,
  onDocumentSelect,
}: DocumentPanelProps) {
  const [documents, setDocuments]     = useState<Document[]>([])
  const [loading, setLoading]         = useState(true)
  const [lastRefresh, setLastRefresh] = useState<Date>(new Date())

  // Preview state
  const [previewDoc, setPreviewDoc]   = useState<Document | null>(null)
  const [pdfUrl, setPdfUrl]           = useState<string | null>(null)
  const [pdfLoading, setPdfLoading]   = useState(false)
  const [pdfError, setPdfError]       = useState<string | null>(null)

  const supabase = createClient()

  // ── Fetch documents ─────────────────────────────────────────────
  const fetchDocuments = useCallback(async () => {
    try {
      const { data, error } = await supabase
        .schema('rag')
        .from('documents')
        .select('id, filename, status, chunk_count, created_at, skipped_pages, doc_metadata')
        .eq('user_id', userId)
        .order('created_at', { ascending: false })

      if (error) throw error
      setDocuments(data ?? [])
      setLastRefresh(new Date())
    } catch (e) {
      console.error('Failed to fetch documents:', e)
    } finally {
      setLoading(false)
    }
  }, [userId, supabase])

  useEffect(() => { fetchDocuments() }, [fetchDocuments])

  // Auto-refresh while any doc is processing
  useEffect(() => {
    const hasActive = documents.some(d => d.status === 'processing' || d.status === 'indexing')
    if (!hasActive) return
    const interval = setInterval(fetchDocuments, 3000)
    return () => clearInterval(interval)
  }, [documents, fetchDocuments])

  // ── Auto-open preview for the initially selected document ────────
  // Runs once after documents first load when activeDocumentId is set
  const hasAutoOpened = useRef(false)
  useEffect(() => {
    if (hasAutoOpened.current || !activeDocumentId || documents.length === 0) return
    const doc = documents.find(d => d.id === activeDocumentId)
    if (doc?.status === 'ready') {
      setPreviewDoc(doc)
      hasAutoOpened.current = true
    }
  }, [documents, activeDocumentId])

  // ── Fetch presigned URL when previewDoc changes ─────────────────
  useEffect(() => {
    if (!previewDoc) {
      setPdfUrl(null)
      setPdfError(null)
      return
    }

    async function fetchUrl() {
      setPdfLoading(true)
      setPdfUrl(null)
      setPdfError(null)
      try {
        const { data: { session } } = await supabase.auth.getSession()
        if (!session) { setPdfError('Not authenticated'); return }

        const res = await fetch(`/api/document-url?document_id=${previewDoc!.id}`, {
          headers: { 'Authorization': `Bearer ${session.access_token}` },
        })

        if (!res.ok) {
          const err = await res.json()
          setPdfError(err.message || 'Failed to load document')
          return
        }

        const data = await res.json()
        setPdfUrl(data.document_url)
      } catch {
        setPdfError('Failed to load document preview')
      } finally {
        setPdfLoading(false)
      }
    }

    fetchUrl()
  }, [previewDoc, supabase])

  // ── Handle card selection ────────────────────────────────────────
  const handleSelect = useCallback((doc: Document) => {
    onDocumentSelect(doc.id, doc.filename)
    if (doc.status === 'ready') {
      setPreviewDoc(doc)
    }
  }, [onDocumentSelect])

  // ── Preview pane (full panel) ────────────────────────────────────
  if (previewDoc) {
    return (
      <div className="flex flex-col h-full w-full border-l border-zinc-800 bg-zinc-900">
        {/* Preview header */}
        <div className="flex items-center justify-between px-3 py-3 border-b border-zinc-800 shrink-0 gap-2">
          <div className="flex items-center gap-2 min-w-0">
            <button
              onClick={() => setPreviewDoc(null)}
              className="p-1 rounded-md text-zinc-400 hover:text-zinc-100 hover:bg-zinc-800 transition-colors shrink-0"
            >
              <ArrowLeft className="w-4 h-4" />
            </button>
            <FileText className="w-4 h-4 text-blue-400 shrink-0" />
            <span className="text-sm font-medium text-zinc-200 truncate">
              {previewDoc.filename}
            </span>
          </div>

          <div className="flex items-center gap-1 shrink-0">
            {pdfUrl && (
              <TooltipProvider>
                <Tooltip>
                  <TooltipTrigger asChild>
                    <a
                      href={pdfUrl}
                      target="_blank"
                      rel="noopener noreferrer"
                      className="p-1.5 rounded-md text-zinc-400 hover:text-zinc-100 hover:bg-zinc-800 transition-colors"
                    >
                      <ExternalLink className="w-3.5 h-3.5" />
                    </a>
                  </TooltipTrigger>
                  <TooltipContent>Open in new tab</TooltipContent>
                </Tooltip>
              </TooltipProvider>
            )}
          </div>
        </div>

        {/* Iframe fills all remaining height */}
        <div className="flex-1 overflow-hidden bg-zinc-950">
          {pdfLoading && (
            <div className="flex flex-col items-center justify-center h-full gap-3 text-zinc-400">
              <Loader2 className="w-8 h-8 animate-spin text-blue-400" />
              <p className="text-sm">Loading preview...</p>
            </div>
          )}

          {pdfError && (
            <div className="flex flex-col items-center justify-center h-full gap-3">
              <AlertCircle className="w-8 h-8 text-red-400" />
              <p className="text-sm text-red-400 text-center px-4">{pdfError}</p>
              <Button variant="outline" size="sm" onClick={() => setPreviewDoc({ ...previewDoc })}>
                Retry
              </Button>
            </div>
          )}

          {pdfUrl && !pdfLoading && !pdfError && (
            <iframe
              src={`${pdfUrl}#toolbar=0&navpanes=0&scrollbar=0&pagemode=none&view=FitH&zoom=page-width`}
              className="w-full h-full"
              title={previewDoc.filename}
            />
          )}
        </div>
      </div>
    )
  }

  // ── List pane ────────────────────────────────────────────────────
  return (
    <div className="flex flex-col h-full w-full border-l border-zinc-800 bg-zinc-900">

      {/* Header */}
      <div className="flex items-center justify-between px-3 py-3 border-b border-zinc-800 shrink-0">
        <div className="flex items-center gap-2">
          <FileText className="w-4 h-4 text-zinc-400" />
          <span className="text-sm font-medium text-zinc-200">Documents</span>
          {documents.length > 0 && (
            <span className="text-xs text-zinc-500 bg-zinc-800 px-1.5 py-0.5 rounded-full">
              {documents.length}
            </span>
          )}
        </div>

        <div className="flex items-center gap-1">
          <TooltipProvider>
            <Tooltip>
              <TooltipTrigger asChild>
                <button
                  onClick={fetchDocuments}
                  className="p-1.5 rounded-md text-zinc-500 hover:text-zinc-300 hover:bg-zinc-800 transition-colors"
                >
                  <RefreshCw className="w-3.5 h-3.5" />
                </button>
              </TooltipTrigger>
              <TooltipContent>Refresh</TooltipContent>
            </Tooltip>
          </TooltipProvider>

        </div>
      </div>

      {/* Upload button */}
      <div className="px-3 py-2 shrink-0">
        <a href="/upload">
          <Button
            variant="outline"
            size="sm"
            className="w-full gap-2 border-dashed border-zinc-600 text-zinc-400 hover:text-zinc-100 hover:border-zinc-400 bg-transparent"
          >
            <Upload className="w-3.5 h-3.5" />
            Upload Document
          </Button>
        </a>
      </div>

      {/* Document list */}
      <ScrollArea className="flex-1 px-3 pb-3">
        {loading ? (
          <div className="flex flex-col gap-2 mt-1">
            {[1, 2, 3].map(i => (
              <div key={i} className="h-20 rounded-lg bg-zinc-800/50 animate-pulse" />
            ))}
          </div>
        ) : documents.length === 0 ? (
          <div className="flex flex-col items-center justify-center py-12 gap-3 text-center">
            <div className="w-12 h-12 rounded-full bg-zinc-800 flex items-center justify-center">
              <FileText className="w-6 h-6 text-zinc-600" />
            </div>
            <div>
              <p className="text-sm text-zinc-400 font-medium">No documents yet</p>
              <p className="text-xs text-zinc-600 mt-1">Upload a PDF to start asking questions</p>
            </div>
          </div>
        ) : (
          <div className="flex flex-col gap-2 mt-1">
            {documents.map(doc => (
              <DocumentCard
                key={doc.id}
                document={doc}
                isActive={activeDocumentId === doc.id}
                onSelect={() => handleSelect(doc)}
              />
            ))}
          </div>
        )}
      </ScrollArea>

      {/* Footer */}
      <div className="px-3 py-2 border-t border-zinc-800 shrink-0">
        <p className="text-xs text-zinc-600">
          Updated {lastRefresh.toLocaleTimeString('en-IN', {
            hour:   '2-digit',
            minute: '2-digit',
            second: '2-digit',
          })}
        </p>
      </div>
    </div>
  )
}
