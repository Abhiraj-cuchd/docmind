'use client';

import { useDocuments } from '@/hooks/useDocuments';
import { UploadZone } from '@/components/documents/UploadZone';
import { DocumentCard } from '@/components/documents/DocumentCard';
import { Skeleton } from '@/components/ui/skeleton';
import { Button } from '@/components/ui/button';
import { ArrowLeft, Files } from '@phosphor-icons/react';
import Link from 'next/link';
import { useRouter } from 'next/navigation';

export default function UploadPage() {
  const { documents, loading, refresh } = useDocuments();
  const router = useRouter();

  const handleUploadComplete = () => {
    refresh();
    setTimeout(() => router.push('/chat'), 1500);
  };

  return (
    <div className="min-h-screen bg-background">
      {/* Top bar */}
      <header className="border-b border-border/50 px-6 py-4 flex items-center gap-4 bg-card/50 backdrop-blur-sm">
        <Link href="/dashboard">
          <Button variant="ghost" size="sm" className="gap-2 text-muted-foreground hover:text-foreground">
            <ArrowLeft className="size-4" />
            Back
          </Button>
        </Link>
        <div className="h-4 w-px bg-border" />
        <div className="flex items-center gap-2">
          <div className="w-6 h-6 rounded-lg bg-primary/10 border border-primary/20 flex items-center justify-center">
            <svg width="12" height="12" viewBox="0 0 24 24" fill="none" className="text-primary">
              <path d="M12 2L2 7l10 5 10-5-10-5zM2 17l10 5 10-5M2 12l10 5 10-5" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round"/>
            </svg>
          </div>
          <span className="text-sm font-bold gradient-text">MindAgent</span>
        </div>
        <h1 className="text-sm font-medium text-muted-foreground ml-1">/ Upload Documents</h1>
      </header>

      <div className="max-w-3xl mx-auto px-6 py-10 space-y-8">
        {/* Upload zone */}
        <section>
          <h2 className="text-lg font-semibold mb-1">Upload a PDF</h2>
          <p className="text-sm text-muted-foreground mb-4">
            Upload your documents to make them searchable with AI. Supported: PDF · Max 50MB
          </p>
          <UploadZone onUploadComplete={handleUploadComplete} />
        </section>

        {/* Existing documents */}
        <section>
          <div className="flex items-center gap-2 mb-4">
            <Files className="size-4 text-muted-foreground" />
            <h2 className="text-sm font-medium">Your Documents</h2>
            <span className="ml-auto text-xs text-muted-foreground">
              {documents.length} file{documents.length !== 1 ? 's' : ''}
            </span>
          </div>

          {loading ? (
            <div className="space-y-3">
              {Array.from({ length: 3 }).map((_, i) => (
                <div key={i} className="flex gap-3 p-3 border border-border rounded-xl">
                  <Skeleton className="w-8 h-8 rounded-lg" />
                  <div className="flex-1 space-y-2">
                    <Skeleton className="h-3 w-2/3" />
                    <Skeleton className="h-2 w-20" />
                  </div>
                </div>
              ))}
            </div>
          ) : documents.length === 0 ? (
            <div className="text-center py-12 border border-dashed border-border rounded-2xl">
              <Files className="size-10 text-muted-foreground/20 mx-auto mb-3" />
              <p className="text-sm text-muted-foreground">No documents uploaded yet</p>
            </div>
          ) : (
            <div className="space-y-2">
              {documents.map(doc => (
                <DocumentCard key={doc.id} document={doc} />
              ))}
            </div>
          )}
        </section>
      </div>
    </div>
  );
}
