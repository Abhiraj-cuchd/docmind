'use client';

import { useCallback, useEffect, useRef, useState } from 'react';
import { supabaseFetch } from '@/lib/supabase';
import { Document } from '@/lib/types';
import { supabase } from '@/lib/supabase';
import { v4 as uuidv4 } from 'uuid';

const POLL_INTERVAL_MS = 5000;
const PROCESSING_STATUSES = ['processing', 'indexing'];

interface UseDocumentsReturn {
  documents: Document[];
  loading: boolean;
  error: string | null;
  createDocument: (params: {
    filename: string;
    userId: string;
  }) => Promise<Document | null>;
  refresh: () => void;
}

export function useDocuments(): UseDocumentsReturn {
  const [documents, setDocuments] = useState<Document[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const pollRef = useRef<ReturnType<typeof setInterval> | null>(null);

  const fetchDocuments = useCallback(async () => {
    try {
      const data = await supabaseFetch<Document[]>(
        'documents?order=created_at.desc'
      );
      setDocuments(data);
      setError(null);
      return data;
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to load documents');
      return [];
    } finally {
      setLoading(false);
    }
  }, []);

  const startPolling = useCallback(() => {
    if (pollRef.current) return;
    pollRef.current = setInterval(async () => {
      const data = await fetchDocuments();
      const hasActive = data.some(d => PROCESSING_STATUSES.includes(d.status));
      if (!hasActive && pollRef.current) {
        clearInterval(pollRef.current);
        pollRef.current = null;
      }
    }, POLL_INTERVAL_MS);
  }, [fetchDocuments]);

  useEffect(() => {
    fetchDocuments().then(data => {
      const hasActive = data.some(d => PROCESSING_STATUSES.includes(d.status));
      if (hasActive) startPolling();
    });

    return () => {
      if (pollRef.current) {
        clearInterval(pollRef.current);
        pollRef.current = null;
      }
    };
  }, [fetchDocuments, startPolling]);

  const createDocument = useCallback(async ({
    filename,
    userId,
  }: { filename: string; userId: string }): Promise<Document | null> => {
    try {
      const docId = uuidv4();
      const s3Key = `uploads/${userId}/${docId}/${filename}`;

      const newDoc: Partial<Document> = {
        id: docId,
        user_id: userId,
        filename,
        s3_key: s3Key,
        status: 'processing',
      };

      const result = await supabaseFetch<Document[]>('documents', {
        method: 'POST',
        headers: { 'Prefer': 'return=representation' },
        body: JSON.stringify(newDoc),
      });

      const created = Array.isArray(result) ? result[0] : result;
      setDocuments(prev => [created, ...prev]);

      // Start polling since a new doc is processing
      startPolling();

      return created;
    } catch (err) {
      console.error('Failed to create document record:', err);
      return null;
    }
  }, [startPolling]);

  return {
    documents,
    loading,
    error,
    createDocument,
    refresh: fetchDocuments,
  };
}
