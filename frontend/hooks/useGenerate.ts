'use client';

import { useCallback, useRef, useState } from 'react';
import api from '@/lib/api';
import { GenerateRequest, GenerateResponse, GeneratePollResult } from '@/lib/types';
import { getAccessToken } from '@/lib/supabase';

const MAX_POLLS = 45;
const POLL_INTERVAL_MS = 2000;

interface UseGenerateReturn {
  generate: (req: GenerateRequest) => Promise<GeneratePollResult | null>;
  isLoading: boolean;
  isPolling: boolean;
  abort: () => void;
}

export function useGenerate(): UseGenerateReturn {
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
    signal: AbortSignal,
  ): Promise<GeneratePollResult | null> => {
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

        const data: GeneratePollResult = await res.json();

        if (data.status === 'done') return data;
        if (data.status === 'error') throw new Error(data.message ?? 'Generation failed on server');
      } catch (err) {
        if ((err as Error).name === 'AbortError') return null;
        console.warn(`[useGenerate] poll attempt ${i + 1} failed:`, err);
      }
    }

    throw new Error('Generation timed out after 90 seconds');
  }, []);

  const generate = useCallback(async (req: GenerateRequest): Promise<GeneratePollResult | null> => {
    abortControllerRef.current?.abort();
    const controller = new AbortController();
    abortControllerRef.current = controller;

    setIsLoading(true);
    setIsPolling(false);

    try {
      const res = await api.post<GenerateResponse>('/api/generate', req, {
        signal: controller.signal,
      });

      setIsPolling(true);
      return await pollResult(res.data.job_id, controller.signal);
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

  return { generate, isLoading, isPolling, abort };
}
