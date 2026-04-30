'use client';

import { useCallback, useEffect, useState } from 'react';
import { supabaseFetch } from '@/lib/supabase';
import { Message } from '@/lib/types';

interface UseMessagesReturn {
  messages: Message[];
  loading: boolean;
  error: string | null;
  addMessage: (msg: Message) => void;
  refresh: () => void;
}

export function useMessages(conversationId: string | null): UseMessagesReturn {
  const [messages, setMessages] = useState<Message[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const fetchMessages = useCallback(async () => {
    if (!conversationId) {
      setMessages([]);
      return;
    }
    setLoading(true);
    try {
      const data = await supabaseFetch<Message[]>(
        `messages?conversation_id=eq.${conversationId}&order=created_at.asc`
      );
      setMessages(data);
      setError(null);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to load messages');
    } finally {
      setLoading(false);
    }
  }, [conversationId]);

  useEffect(() => {
    fetchMessages();
  }, [fetchMessages]);

  const addMessage = useCallback((msg: Message) => {
    setMessages(prev => [...prev, msg]);
  }, []);

  return {
    messages,
    loading,
    error,
    addMessage,
    refresh: fetchMessages,
  };
}
