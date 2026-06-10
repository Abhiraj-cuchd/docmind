'use client';

import { useCallback, useEffect, useState } from 'react';
import api from '@/lib/api';
import { Summary } from '@/lib/types';

interface UseSummariesReturn {
  summaries: Summary[];
  loading: boolean;
  error: string | null;
  refresh: () => void;
}

interface UseSummariesOptions {
  conversation_id?: string;
  document_id?: string;
  enabled?: boolean;
}

export function useSummaries({
  conversation_id,
  document_id,
  enabled = true,
}: UseSummariesOptions): UseSummariesReturn {
  const [summaries, setSummaries] = useState<Summary[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const param = conversation_id
    ? `conversation_id=${conversation_id}`
    : document_id
    ? `document_id=${document_id}`
    : null;

  const fetch = useCallback(async () => {
    if (!param) return;
    setLoading(true);
    try {
      const res = await api.get<{ summaries: Summary[] }>(`/api/summaries?${param}`);
      setSummaries(res.data.summaries);
      setError(null);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to load summary');
    } finally {
      setLoading(false);
    }
  }, [param]);

  useEffect(() => {
    if (enabled && param) {
      fetch();
    }
  }, [enabled, param, fetch]);

  return { summaries, loading, error, refresh: fetch };
}
