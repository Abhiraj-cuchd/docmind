'use client';

import { useState } from 'react';
import { Document } from '@/lib/types';
import { DocumentStatusBadge } from './DocumentStatus';
import { FilePdf, Rows, Warning, Trash } from '@phosphor-icons/react';
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog';
import { Button } from '@/components/ui/button';

interface DocumentCardProps {
  document: Document;
  onDelete?: (id: string) => Promise<boolean>;
}

export function DocumentCard({ document: doc, onDelete }: DocumentCardProps) {
  const [confirmOpen, setConfirmOpen] = useState(false);
  const [deleting, setDeleting] = useState(false);

  const handleConfirm = async () => {
    if (!onDelete) return;
    setDeleting(true);
    await onDelete(doc.id);
    setDeleting(false);
    setConfirmOpen(false);
  };

  return (
    <>
      <div className="group flex items-center gap-3 px-3 py-2.5 rounded-xl border border-border/50 bg-card hover:border-border transition-colors">
        <div className="w-8 h-8 rounded-lg bg-red-500/10 border border-red-500/20 flex items-center justify-center shrink-0">
          <FilePdf className="size-4 text-red-400" weight="fill" />
        </div>

        <div className="flex-1 min-w-0">
          <p className="text-xs font-medium truncate text-foreground" title={doc.filename}>
            {doc.filename}
          </p>

          <div className="flex items-center gap-2 mt-1 flex-wrap">
            <DocumentStatusBadge status={doc.status} />

            {doc.chunk_count !== undefined && doc.status === 'ready' && (
              <span className="flex items-center gap-0.5 text-[10px] text-muted-foreground">
                <Rows className="size-2.5" />
                {doc.chunk_count} chunks
              </span>
            )}
          </div>

          {doc.skipped_pages !== undefined && doc.skipped_pages > 0 && (
            <p className="flex items-center gap-1 text-[10px] text-amber-400 mt-1">
              <Warning className="size-2.5" />
              {doc.skipped_pages} page{doc.skipped_pages > 1 ? 's' : ''} skipped
            </p>
          )}
        </div>

        {onDelete && (
          <button
            onClick={() => setConfirmOpen(true)}
            className="shrink-0 p-1.5 rounded-lg text-muted-foreground/40 hover:text-red-400 hover:bg-red-500/10 opacity-0 group-hover:opacity-100 transition-all"
            title="Delete document"
          >
            <Trash className="size-3.5" />
          </button>
        )}
      </div>

      <Dialog open={confirmOpen} onOpenChange={open => { if (!deleting) setConfirmOpen(open) }}>
        <DialogContent className="max-w-sm">
          <DialogHeader>
            <DialogTitle className="flex items-center gap-2">
              <Trash className="size-4 text-red-400" />
              Delete Document
            </DialogTitle>
            <DialogDescription className="text-sm leading-relaxed">
              <span className="font-medium text-foreground block truncate mb-2">
                {doc.filename}
              </span>
              This will permanently delete the document and{' '}
              <span className="text-red-400 font-medium">all conversations</span>{' '}
              associated with it. This action cannot be undone.
            </DialogDescription>
          </DialogHeader>
          <DialogFooter className="gap-2 sm:gap-2">
            <Button
              variant="outline"
              size="sm"
              onClick={() => setConfirmOpen(false)}
              disabled={deleting}
            >
              Cancel
            </Button>
            <Button
              size="sm"
              onClick={handleConfirm}
              disabled={deleting}
              className="bg-red-600 hover:bg-red-700 text-white border-0"
            >
              {deleting ? 'Deleting…' : 'Delete'}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </>
  );
}
