'use client'

import { useDocuments } from '@/hooks/useDocuments'
import { useAuth } from '@/hooks/useAuth'
import { useMemo, useState } from 'react'
import { Document } from '@/lib/types'
import {
  FileText, Upload, CheckCircle, AlertCircle,
  Loader2, Hash, ArrowRight, RefreshCw, User, ChevronDown
} from 'lucide-react'
import { Button } from '@/components/ui/button'
import Link from 'next/link'
import { cn } from '@/lib/utils'

interface Props {
  onSelect: (documentId: string, filename: string) => void
}

function formatDate(dateStr: string): string {
  return new Date(dateStr).toLocaleDateString('en-IN', {
    day: '2-digit', month: 'short', year: 'numeric',
  })
}

type StatusKey = Document['status']

const STATUS_CONFIG: Record<StatusKey, { label: string; color: string; bg: string; iconClass: string }> = {
  ready:      { label: 'Ready',      color: 'text-emerald-400', bg: 'bg-emerald-500/10 border-emerald-500/20', iconClass: '' },
  processing: { label: 'Processing', color: 'text-amber-400',   bg: 'bg-amber-500/10 border-amber-500/20',     iconClass: 'animate-spin' },
  indexing:   { label: 'Indexing',   color: 'text-blue-400',    bg: 'bg-blue-500/10 border-blue-500/20',       iconClass: 'animate-spin' },
  failed:     { label: 'Failed',     color: 'text-red-400',     bg: 'bg-red-500/10 border-red-500/20',         iconClass: '' },
}

function StatusIcon({ status }: { status: StatusKey }) {
  switch (status) {
    case 'ready':      return <CheckCircle className="w-3 h-3" />
    case 'processing':
    case 'indexing':   return <Loader2 className="w-3 h-3" />
    case 'failed':     return <AlertCircle className="w-3 h-3" />
  }
}

function DocumentGridCard({
  doc,
  onClick,
  index,
}: {
  doc: Document
  onClick: () => void
  index: number
}) {
  const isReady = doc.status === 'ready'
  const { label, color, iconClass } = STATUS_CONFIG[doc.status]

  return (
    <button
      onClick={isReady ? onClick : undefined}
      disabled={!isReady}
      style={{ animationDelay: `${index * 55}ms` }}
      className={cn(
        'group relative flex flex-col gap-3 p-5 rounded-2xl border text-left w-full',
        'animate-in fade-in-0 slide-in-from-bottom-3 duration-300 fill-mode-both',
        isReady
          ? [
              'border-border bg-card cursor-pointer',
              'hover:border-primary/50 hover:bg-primary/[0.04]',
              'hover:-translate-y-1 hover:shadow-xl hover:shadow-primary/10',
              'transition-all duration-200',
            ]
          : 'border-border/40 bg-card/40 cursor-not-allowed opacity-55'
      )}
    >
      {/* Icon block */}
      <div className="flex items-start justify-between">
        <div className="w-11 h-11 rounded-xl bg-red-500/10 border border-red-500/20 flex items-center justify-center shrink-0">
          <FileText className="w-5 h-5 text-red-400" />
        </div>

        {/* Arrow appears on hover for ready docs */}
        {isReady && (
          <ArrowRight className="w-4 h-4 text-primary opacity-0 group-hover:opacity-100 transition-opacity duration-150 mt-1 shrink-0" />
        )}
      </div>

      {/* Filename + date */}
      <div className="flex-1 min-w-0 space-y-0.5">
        <p
          className="text-sm font-semibold text-foreground leading-snug line-clamp-2"
          title={doc.filename}
        >
          {doc.filename}
        </p>
        <p className="text-xs text-muted-foreground">{formatDate(doc.created_at)}</p>
      </div>

      {/* Footer: status + chunk count */}
      <div className="flex items-center justify-between gap-2 pt-1 border-t border-border/50">
        <span className={cn('flex items-center gap-1.5 text-xs font-medium', color)}>
          <span className={iconClass}>
            <StatusIcon status={doc.status} />
          </span>
          {label}
        </span>

        {doc.chunk_count !== undefined && isReady && (
          <span className="flex items-center gap-1 text-xs text-muted-foreground">
            <Hash className="w-3 h-3" />
            {doc.chunk_count.toLocaleString()} chunks
          </span>
        )}
      </div>
    </button>
  )
}

function SkeletonCard({ index }: { index: number }) {
  return (
    <div
      style={{ animationDelay: `${index * 50}ms` }}
      className="animate-in fade-in-0 duration-300 fill-mode-both h-44 rounded-2xl bg-card border border-border"
    >
      <div className="p-5 h-full flex flex-col gap-3">
        <div className="w-11 h-11 rounded-xl bg-muted animate-pulse" />
        <div className="flex-1 space-y-2">
          <div className="h-3 bg-muted rounded animate-pulse w-3/4" />
          <div className="h-2.5 bg-muted rounded animate-pulse w-1/2" />
        </div>
        <div className="h-2.5 bg-muted rounded animate-pulse w-1/3" />
      </div>
    </div>
  )
}

export function DocumentSelectionScreen({ onSelect }: Props) {
  const { documents, loading, refresh } = useDocuments()
  const { user } = useAuth()
  const [agentOpen, setAgentOpen] = useState(false)
  const [agentValue, setAgentValue] = useState('rag')
  const agentOptions = useMemo(() => (
    [
      { value: 'rag', label: 'RAG Agent' },
      { value: 'travel', label: 'Travel Planner Agent' },
      { value: 'hr', label: 'HR Assistant (Org Scoped)' },
      { value: 'diet', label: 'Diet Planner Agent' },
      { value: 'citation', label: 'Citation Finder Agent' },
    ]
  ), [])
  const activeAgentLabel = agentOptions.find(option => option.value === agentValue)?.label ?? 'RAG Agent'
  const readyCount = documents.filter(d => d.status === 'ready').length
  const displayName =
    (user?.user_metadata?.full_name as string | undefined) ??
    (user?.user_metadata?.name as string | undefined) ??
    user?.email?.split('@')[0] ??
    'User'

  return (
    <div className="min-h-screen bg-background flex flex-col">

      {/* ── Header ─────────────────────────────────────────────────── */}
      <header className="sticky top-0 z-10 border-b border-border/50 bg-background/80 backdrop-blur-md">
        <div className="w-full px-6 h-16 flex items-center justify-start gap-4">
          <div className="flex items-center gap-2">
            <label htmlFor="agent-selector" className="text-xs text-muted-foreground">
              Choose Your Agent:
            </label>
            <div className="relative">
              <button
                id="agent-selector"
                type="button"
                onClick={() => setAgentOpen(prev => !prev)}
                className="h-9 min-w-[260px] rounded-xl border border-primary/40 bg-primary/10 px-3 text-sm text-foreground text-left shadow-sm shadow-primary/10 focus:outline-none focus:ring-2 focus:ring-primary/40"
                aria-haspopup="listbox"
                aria-expanded={agentOpen}
              >
                <span className="flex items-center justify-between gap-2">
                  <span className="font-semibold">{activeAgentLabel}</span>
                  <ChevronDown className={cn('w-4 h-4 text-primary transition-transform', agentOpen && 'rotate-180')} />
                </span>
              </button>
              {agentOpen && (
                <div
                  role="listbox"
                  className="absolute left-0 mt-2 w-full rounded-xl border border-border bg-popover shadow-xl z-20 overflow-hidden"
                >
                  {agentOptions.map(option => (
                    <button
                      key={option.value}
                      type="button"
                      role="option"
                      aria-selected={option.value === agentValue}
                      onMouseDown={() => {
                        setAgentValue(option.value)
                        setAgentOpen(false)
                      }}
                      className={cn(
                        'w-full text-left px-3 py-2.5 text-sm hover:bg-accent transition-colors',
                        option.value === agentValue && 'bg-accent text-foreground'
                      )}
                    >
                      {option.label}
                    </button>
                  ))}
                </div>
              )}
            </div>
          </div>

          <div className="ml-auto flex items-center gap-2">
            <button
              onClick={refresh}
              className="p-2 rounded-lg text-muted-foreground hover:text-foreground hover:bg-accent transition-colors"
            >
              <RefreshCw className="w-4 h-4" />
            </button>
            <Link href="/upload">
              <Button size="sm" className="gap-2 h-8 text-xs">
                <Upload className="w-3.5 h-3.5" />
                Upload
              </Button>
            </Link>
            <div className="flex items-center gap-2 px-2 py-1 rounded-lg border border-border bg-card/60">
              <div className="w-7 h-7 rounded-full bg-primary/10 border border-primary/20 flex items-center justify-center">
                <User className="w-4 h-4 text-primary" />
              </div>
              <div className="min-w-0">
                <p className="text-xs font-medium text-foreground truncate max-w-[140px]">
                  {displayName}
                </p>
                <p className="text-[10px] text-muted-foreground truncate max-w-[140px]">
                  {user?.email ?? 'No email'}
                </p>
              </div>
            </div>
          </div>
        </div>
      </header>

      {/* ── Main ───────────────────────────────────────────────────── */}
      <main className="flex-1 w-full px-6 py-12">

        {/* Page heading */}
        <div
          className="mb-10 animate-in fade-in-0 slide-in-from-bottom-2 duration-400 fill-mode-both"
          style={{ animationDelay: '0ms' }}
        >
          <h1 className="text-3xl font-bold tracking-tight text-foreground">
            Your Documents
          </h1>
          <p className="mt-2 text-sm text-muted-foreground">
            {loading
              ? 'Loading your library…'
              : documents.length === 0
                ? 'Upload a PDF to get started'
                : readyCount > 0
                  ? `${readyCount} document${readyCount !== 1 ? 's' : ''} ready — select one to start chatting`
                  : 'Your documents are still processing'}
          </p>
        </div>

        {/* Loading skeletons */}
        {loading && (
          <div className="grid grid-cols-2 md:grid-cols-3 gap-4">
            {Array.from({ length: 6 }).map((_, i) => (
              <SkeletonCard key={i} index={i} />
            ))}
          </div>
        )}

        {/* Empty state */}
        {!loading && documents.length === 0 && (
          <div
            className="flex flex-col items-center justify-center py-28 gap-5 text-center animate-in fade-in-0 duration-500 fill-mode-both"
          >
            <div className="w-20 h-20 rounded-3xl bg-card border border-border flex items-center justify-center">
              <FileText className="w-10 h-10 text-muted-foreground/25" />
            </div>
            <div className="space-y-1">
              <p className="text-base font-semibold text-foreground">No documents yet</p>
              <p className="text-sm text-muted-foreground">
                Upload a PDF to start asking questions
              </p>
            </div>
            <Link href="/upload">
              <Button className="gap-2 mt-1">
                <Upload className="w-4 h-4" />
                Upload your first document
              </Button>
            </Link>
          </div>
        )}

        {/* Document grid */}
        {!loading && documents.length > 0 && (
          <div className="grid grid-cols-2 md:grid-cols-3 gap-4">
            {documents.map((doc, i) => (
              <DocumentGridCard
                key={doc.id}
                doc={doc}
                index={i}
                onClick={() => onSelect(doc.id, doc.filename)}
              />
            ))}
          </div>
        )}
      </main>
    </div>
  )
}
