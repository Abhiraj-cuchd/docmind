'use client';

import { useCallback, useEffect, useState } from 'react';
import { supabaseFetch, getAccessToken } from '@/lib/supabase';
import { Conversation } from '@/lib/types';
import { v4 as uuidv4 } from 'uuid';
import { supabase } from '@/lib/supabase';

interface UseConversationsReturn {
  conversations: Conversation[];
  loading: boolean;
  error: string | null;
  createConversation: (title?: string, documentId?: string) => Promise<Conversation | null>;
  deleteConversation: (id: string) => Promise<boolean>;
  refresh: () => void;
}

export function useConversations(): UseConversationsReturn {
  const [conversations, setConversations] = useState<Conversation[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const fetchConversations = useCallback(async () => {
    try {
      const data = await supabaseFetch<Conversation[]>(
        'conversations?order=updated_at.desc'
      );
      setConversations(data);
      setError(null);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to load conversations');
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    fetchConversations();
  }, [fetchConversations]);

  const createConversation = useCallback(async (title = 'New Conversation', documentId?: string): Promise<Conversation | null> => {
    try {
      const { data: { session } } = await supabase.auth.getSession();
      if (!session) return null;

      const newConv: Partial<Conversation> = {
        id: uuidv4(),
        user_id: session.user.id,
        title,
      };

      if (documentId) {
        newConv.document_id = documentId;
      }

      const result = await supabaseFetch<Conversation[]>('conversations', {
        method: 'POST',
        headers: {
          'Prefer': 'return=representation',
        },
        body: JSON.stringify(newConv),
      });

      const created = Array.isArray(result) ? result[0] : result;
      setConversations(prev => [created, ...prev]);
      return created;
    } catch (err) {
      console.error('Failed to create conversation:', err);
      return null;
    }
  }, []);

  const deleteConversation = useCallback(async (id: string): Promise<boolean> => {
    const previous = conversations;
    setConversations(prev => prev.filter(c => c.id !== id));
    try {
      const token = await getAccessToken();
      if (!token) throw new Error('Not authenticated');

      const res = await fetch(`/api/conversations/${id}`, {
        method: 'DELETE',
        headers: { Authorization: `Bearer ${token}` },
      });

      if (!res.ok) throw new Error(`Delete failed: ${res.status}`);
      return true;
    } catch (err) {
      console.error('Failed to delete conversation:', err);
      setConversations(previous);
      return false;
    }
  }, [conversations]);

  return {
    conversations,
    loading,
    error,
    createConversation,
    deleteConversation,
    refresh: fetchConversations,
  };
}
