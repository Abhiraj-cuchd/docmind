'use client';

import { useCallback, useRef, useState } from 'react';
import api from '@/lib/api';
import { PollResult, QueryRequest, QueryResponse } from '@/lib/types';
import { getAccessToken } from '@/lib/supabase';

const MAX_POLLS = 45;
const POLL_INTERVAL_MS = 2000;

interface UseRAGQueryReturn {
  submit: (req: QueryRequest) => Promise<PollResult | null>;
  isLoading: boolean;
  isPolling: boolean;
  abort: () => void;
}

export function useRAGQuery(): UseRAGQueryReturn {
  const [isLoading, setIsLoading] = useState(false);
  const [isPolling, setIsPolling] = useState(false);
  const abortControllerRef = useRef<AbortController | null>(null);

  const abort = useCallback(() => {
    abortControllerRef.current?.abort();
    setIsLoading(false);
    setIsPolling(false);
  }, []);

  const pollResult = useCallback(async (
    jobId: string,
    signal: AbortSignal
  ): Promise<PollResult | null> => {
    for (let i = 0; i < MAX_POLLS; i++) {
      if (signal.aborted) return null;

      await new Promise(res => setTimeout(res, POLL_INTERVAL_MS));
      if (signal.aborted) return null;

      try {
        const token = await getAccessToken();
        const res = await fetch(`/api/result/${jobId}`, {
          headers: token ? { Authorization: `Bearer ${token}` } : {},
          signal,
        });

        if (!res.ok) continue;

        const data: PollResult = await res.json();

        if (data.status === 'done') return data;
        if (data.status === 'error') throw new Error('Query failed on server');
      } catch (err) {
        if ((err as Error).name === 'AbortError') return null;
        // Continue polling on network errors
        console.warn(`Poll attempt ${i + 1} failed:`, err);
      }
    }

    throw new Error('Query timed out after 90 seconds');
  }, []);

  const submit = useCallback(async (req: QueryRequest): Promise<PollResult | null> => {
    // Abort any in-flight request
    abortControllerRef.current?.abort();
    const controller = new AbortController();
    abortControllerRef.current = controller;

    setIsLoading(true);
    setIsPolling(false);

    try {
      const res = await api.post<QueryResponse>('/api/query', req, {
        signal: controller.signal,
      });

      const response = res.data;

      // Case 1: instant answer (cache hit or conversational)
      if (!response.job_id && response.status === 'done') {
        return {
          status: 'done',
          answer: response.answer ?? '',
          cached: response.cached ?? false,
          voice_url: response.voice_url ?? null,
          voice_urls: response.voice_urls ?? null,
          voice_credits_remaining: response.voice_credits_remaining ?? 0,
          tokens_used: response.tokens_used ?? 0,
          path: response.path ?? 'conversational',
          sources: response.sources,
        };
      }

      // Case 2: async job — start polling
      if (response.job_id) {
        setIsPolling(true);
        const result = await pollResult(response.job_id, controller.signal);
        return result;
      }

      return null;
    } catch (err) {
      if ((err as Error).name === 'AbortError' || (err as Error).name === 'CanceledError') {
        return null;
      }
      throw err;
    } finally {
      setIsLoading(false);
      setIsPolling(false);
    }
  }, [pollResult]);

  return { submit, isLoading, isPolling, abort };
}
