'use client';

import { useState, useCallback } from 'react';
import { ChunkEvidence } from '@/lib/types';

export interface ActiveHighlight {
  documentId: string | null;
  pageNumber: number;
  content: string;
}

export function usePDFHighlight() {
  const [activeHighlight, setActiveHighlight] = useState<ActiveHighlight | null>(null);

  const triggerHighlight = useCallback((evidence: ChunkEvidence) => {
    setActiveHighlight({
      documentId: evidence.document_id,
      pageNumber: evidence.page_number ?? 1,
      content: evidence.content,
    });
  }, []);

  const clearHighlight = useCallback(() => {
    setActiveHighlight(null);
  }, []);

  return { activeHighlight, triggerHighlight, clearHighlight };
}
