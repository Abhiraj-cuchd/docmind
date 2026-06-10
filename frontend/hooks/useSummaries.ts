'use client';

import { useQuery } from '@tanstack/react-query';
import api from '@/lib/api';
import { Summary } from '@/lib/types';

interface SummariesResponse {
  summaries: Summary[];
}

interface UseSummariesOptions {
  conversation_id?: string;
  document_id?: string;
  enabled?: boolean;
}

export function useSummaries({ conversation_id, document_id, enabled = true }: UseSummariesOptions) {
  const param = conversation_id
    ? `conversation_id=${conversation_id}`
    : document_id
    ? `document_id=${document_id}`
    : null;

  return useQuery<Summary[]>({
    queryKey: ['summaries', conversation_id ?? null, document_id ?? null],
    queryFn: async () => {
      const res = await api.get<SummariesResponse>(`/api/summaries?${param}`);
      return res.data.summaries;
    },
    enabled: enabled && !!param,
    staleTime: 1000 * 60 * 5,
  });
}
